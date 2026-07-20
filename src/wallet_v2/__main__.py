"""Operator commands for controlled Wallet V2 runs."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date

from sqlalchemy import Engine, select

from wallet_v2.adapters import ImapMailboxReader, OpenAICompatibleExtractor
from wallet_v2.adapters.wallet_api import BudgetBakersWalletClient
from wallet_v2.application.account_repair import AccountRepairService
from wallet_v2.application.catalog_sync import CatalogSyncService, CatalogReader
from wallet_v2.application.service import WalletWorkflow
from wallet_v2.config import ConfigError, load_settings
from wallet_v2.domain.enums import IntegrationMode
from wallet_v2.persistence.models import ExecutionRun
from wallet_v2.persistence.session import (
    create_engine_from_settings,
    create_session_factory,
    session_scope,
)


def _parse_uids(value: str) -> tuple[int, ...]:
    try:
        uids = tuple(int(uid.strip()) for uid in value.split(",") if uid.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--uids must be comma-separated positive integers") from exc
    if not uids or any(uid < 1 for uid in uids):
        raise argparse.ArgumentTypeError("--uids must be comma-separated positive integers")
    return uids


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wallet-v2")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="fetch and create review tasks")
    run.add_argument("--label", required=True, help="human-readable execution label")
    run.add_argument("--mode", choices=[mode.value for mode in IntegrationMode], required=True)
    run.add_argument("--trigger", choices=["manual", "scheduled", "test"], default="manual")
    run.add_argument("--limit", type=int, default=5, help="maximum unseen messages to inspect")
    selection = run.add_mutually_exclusive_group()
    selection.add_argument(
        "--on-date",
        type=date.fromisoformat,
        help="process every message whose IMAP internal date is YYYY-MM-DD",
    )
    selection.add_argument(
        "--uids",
        type=_parse_uids,
        help="reprocess only these comma-separated IMAP UIDs",
    )
    run.add_argument(
        "--reprocess",
        action="store_true",
        help="create fresh attempts for explicit --uids rather than deduplicating them",
    )

    runs = subcommands.add_parser("runs", help="inspect recorded execution runs")
    runs_subcommands = runs.add_subparsers(dest="runs_command", required=True)
    show = runs_subcommands.add_parser("show", help="show one execution run")
    show.add_argument("run_id")

    subcommands.add_parser("sync-catalog", help="sync Wallet catalog resources to versioned local snapshots")

    repair = subcommands.add_parser("repair-qik", help="merge duplicate Qik FinancialAccounts and map to a Wallet account")
    repair.add_argument(
        "--raw-references", nargs="+", required=True,
        help="one or more raw external references that share a canonical form (e.g. *2197 ************2197)",
    )
    repair.add_argument(
        "--wallet-account-id",
        required=True,
        help="Wallet account ID to map the surviving FinancialAccount to",
    )
    repair.add_argument(
        "--issuer",
        required=True,
        help="exact issuer name recorded on the local FinancialAccount rows",
    )
    return parser


def _require_processing_integrations(settings: object) -> None:
    mailbox = getattr(settings, "mailbox")
    llm = getattr(settings, "llm")
    if mailbox.mode is IntegrationMode.DISABLED:
        raise ConfigError("MAILBOX__MODE must not be disabled for a processing run")
    if llm.mode is IntegrationMode.DISABLED:
        raise ConfigError("LLM__MODE must not be disabled for a processing run")


def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    _require_processing_integrations(settings)
    if args.limit < 1:
        raise ValueError("--limit must be >= 1")
    if args.reprocess and not args.uids:
        raise ValueError("--reprocess requires explicit --uids")
    run_mode = IntegrationMode(args.mode)
    if run_mode is IntegrationMode.DISABLED:
        raise ValueError("a processing run must use dry_run or live mode")
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    run_id: uuid.UUID | None = None
    try:
        # Commit the run identity before performing network I/O. If a provider
        # call fails, the separate failure transaction below leaves an
        # inspectable run record rather than rolling it back with message work.
        with session_scope(factory) as session:
            workflow = WalletWorkflow(session)
            run = workflow.start_run(
                mode=run_mode,
                trigger=args.trigger,
                label=args.label,
                metadata={
                    "mailbox_mode": settings.mailbox.mode.value,
                    "llm_mode": settings.llm.mode.value,
                    "wallet_mode": settings.wallet.mode.value,
                    "selection": (
                        {"kind": "all_messages_on_date", "date": args.on_date.isoformat()}
                        if args.on_date
                        else (
                            {"kind": "explicit_uids", "uids": list(args.uids)}
                            if args.uids
                            else {"kind": "recent_unseen", "limit": args.limit}
                        )
                    ),
                },
            )
            run_id = run.id
        mailbox = ImapMailboxReader(
            host=settings.mailbox.host or "",
            port=settings.mailbox.port or 0,
            username=settings.mailbox.username or "",
            password=settings.mailbox.password or "",
        )
        extractor = OpenAICompatibleExtractor(
            provider=settings.llm.provider or "",
            model=settings.llm.model or "",
            api_key=settings.llm.api_key or "",
            timeout_seconds=settings.llm.timeout_seconds,
            base_url=settings.llm.base_url,
        )
        messages = (
            mailbox.fetch_on_date(day=args.on_date)
            if args.on_date
            else (
                mailbox.fetch_uids(uids=args.uids)
                if args.uids
                else mailbox.fetch_unseen(limit=args.limit)
            )
        )
        created_candidates = 0
        consulted_messages: list[dict[str, object]] = []
        message_failures: list[dict[str, object]] = []
        for message in messages:
            message_summary = {
                "uid_validity": message.uid_validity,
                "message_uid": message.message_uid,
                "message_id": message.message_id_header,
                "sender": message.sender,
                "subject": message.subject,
            }
            consulted_messages.append(message_summary)
            try:
                # A historical selection can include malformed or unsupported
                # receipts. Commit each successful message independently so a
                # single bad extraction cannot erase valid candidates.
                with session_scope(factory) as session:
                    run = session.get(ExecutionRun, run_id)
                    if run is None:
                        raise RuntimeError("execution run disappeared after creation")
                    workflow = WalletWorkflow(session)
                    process = workflow.reprocess if args.reprocess else workflow.ingest_and_extract
                    _, candidates, _ = process(run=run, message=message, extractor=extractor)
                    created_candidates += len(candidates)
            except Exception as exc:
                message_failures.append(
                    {
                        "message_uid": message.message_uid,
                        "error_kind": type(exc).__name__,
                    }
                )
        with session_scope(factory) as session:
            run = session.get(ExecutionRun, run_id)
            if run is None:
                raise RuntimeError("execution run disappeared before completion")
            workflow = WalletWorkflow(session)
            if message_failures:
                workflow.finish_run(
                    run,
                    outcome="failed",
                    error=f"{len(message_failures)} message(s) failed; inspect run output",
                )
            else:
                workflow.finish_run(run, outcome="succeeded")
            result = {
                "execution_run_id": str(run.id),
                "mode": str(run.mode),
                "trigger": run.trigger,
                "label": run.label,
                "selection": run.metadata_json["selection"] if run.metadata_json else None,
                "messages_consulted": consulted_messages,
                "review_candidates_created": created_candidates,
                "message_failures": message_failures,
                "wallet_submission": "not attempted; review approval is required",
            }
        print(json.dumps(result, sort_keys=True))
        return 1 if message_failures else 0
    except Exception as exc:
        if run_id is not None:
            with session_scope(factory) as session:
                run = session.get(ExecutionRun, run_id)
                if run is not None and run.outcome == "running":
                    WalletWorkflow(session).finish_run(
                        run, outcome="failed", error=str(exc)[:2048]
                    )
        raise
    finally:
        engine.dispose()


def _show_run(args: argparse.Namespace) -> int:
    settings = load_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            run = session.scalar(select(ExecutionRun).where(ExecutionRun.id == uuid.UUID(args.run_id)))
            if run is None:
                print(f"execution run not found: {args.run_id}", file=sys.stderr)
                return 2
            print(
                json.dumps(
                    {
                        "id": str(run.id),
                        "mode": str(run.mode),
                        "trigger": run.trigger,
                        "label": run.label,
                        "initiator": run.initiator,
                        "metadata": run.metadata_json,
                        "started_at": run.started_at.isoformat(),
                        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                        "outcome": run.outcome,
                        "error_summary": run.error_summary,
                    },
                    sort_keys=True,
                )
            )
        return 0
    finally:
        engine.dispose()


def _sync_catalog(
    args: argparse.Namespace,
    *,
    _settings: Settings | None = None,
    _client: CatalogReader | None = None,
    _engine: Engine | None = None,
) -> int:
    settings = _settings or load_settings()
    if settings.wallet.mode is IntegrationMode.DISABLED:
        raise ConfigError("WALLET__MODE must not be disabled for catalog sync")
    engine = _engine or create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    try:
        client = _client or BudgetBakersWalletClient(
            base_url=settings.wallet.base_url or "",
            api_key=settings.wallet.api_key or "",
            timeout_seconds=settings.wallet.timeout_seconds,
        )
        with session_scope(factory) as session:
            service = CatalogSyncService(session=session, reader=client)
            snapshots = service.sync_all()
            result = {
                "mode": settings.wallet.mode.value,
                "provider_revision": client.last_revision(),
                "snapshots": {
                    kind: {
                        "snapshot_id": str(snap.id),
                        "snapshot_version": snap.snapshot_version,
                        "item_count": snap.catalog_data["item_count"],
                    }
                    for kind, snap in snapshots.items()
                },
            }
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        engine.dispose()


def _repair_qik(args: argparse.Namespace) -> int:
    settings = load_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            svc = AccountRepairService(session)
            result = svc.repair_qik_account(
                raw_references=args.raw_references,
                wallet_account_id=args.wallet_account_id,
                issuer=args.issuer,
            )
            output = {
                "survivor_account_id": result.survivor_account_id,
                "merged_account_ids": result.merged_account_ids,
                "reassigned": result.reassigned,
                "mapping_account_id": result.mapping_account_id,
                "mapping_remote_id": result.mapping_remote_id,
            }
            if result.warnings:
                output["warnings"] = result.warnings
            print(json.dumps(output, sort_keys=True))
        return 0
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "sync-catalog":
            return _sync_catalog(args)
        if args.command == "repair-qik":
            return _repair_qik(args)
        return _show_run(args)
    except (ConfigError, ValueError, RuntimeError) as exc:
        print(f"wallet-v2: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
