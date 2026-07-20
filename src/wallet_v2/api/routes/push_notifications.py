"""Push notification configuration and subscription API.

Endpoints are unauthenticated (single-operator boundary). The push config
endpoint reveals only the public key and whether push is enabled — never
the private key or subject.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wallet_v2.api.deps import get_session
from wallet_v2.api.schemas import (
    DisableSubscriptionResponse,
    PushConfigResponse,
    RegisterSubscriptionRequest,
    RegisterSubscriptionResponse,
    SubscriptionStatusResponse,
    SubscriptionView,
)
from wallet_v2.config import PushSettings, Settings
from wallet_v2.persistence.models.push_subscription import PushSubscription

router = APIRouter(prefix="/push", tags=["push"])


def _push_settings(request: Request) -> PushSettings:
    settings: Settings = request.app.state.settings
    return settings.push


@router.get("/config", response_model=PushConfigResponse)
def get_push_config(
    request: Request,
) -> PushConfigResponse:
    """Return the runtime push configuration for the PWA frontend.

    The ``public_key`` is the VAPID application server public key (not a
    secret). ``enabled`` is ``True`` only when the push integration is
    configured for ``dry_run`` or ``live`` mode.
    """
    ps = _push_settings(request)
    return PushConfigResponse(
        enabled=ps.enabled,
        public_key=ps.public_key,
        fcm_project_id=ps.fcm_project_id,
    )


@router.post(
    "/subscriptions", response_model=RegisterSubscriptionResponse, status_code=201
)
def register_subscription(
    body: RegisterSubscriptionRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> RegisterSubscriptionResponse:
    """Register or re-register a browser push subscription.

    If the endpoint already exists the credential keys are updated in-place
    (p256dh / auth rotation). This allows the same browser to re-subscribe
    without creating duplicate records.
    """
    ps = _push_settings(request)
    if not ps.enabled:
        raise HTTPException(status_code=400, detail="Push notifications are disabled")

    existing = session.execute(
        select(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.keys_p256dh = body.keys_p256dh
        existing.keys_auth = body.keys_auth
        if body.user_agent is not None:
            existing.user_agent = body.user_agent
        existing.status = "active"
        existing.disabled_at = None
        existing.disabled_reason = None
        session.flush()
        return RegisterSubscriptionResponse(
            subscription_id=existing.id, status=existing.status
        )

    sub = PushSubscription(
        id=uuid.uuid4(),
        endpoint=body.endpoint,
        keys_p256dh=body.keys_p256dh,
        keys_auth=body.keys_auth,
        user_agent=body.user_agent,
    )
    session.add(sub)
    session.flush()
    return RegisterSubscriptionResponse(
        subscription_id=sub.id, status=sub.status
    )


@router.post(
    "/subscriptions/{subscription_id}/disable",
    response_model=DisableSubscriptionResponse,
)
def disable_subscription(
    subscription_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> DisableSubscriptionResponse:
    """Disable a previously registered push subscription."""
    ps = _push_settings(request)
    if not ps.enabled:
        raise HTTPException(status_code=400, detail="Push notifications are disabled")

    sub = session.get(PushSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.status != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Subscription is already {sub.status}, not active",
        )

    sub.status = "disabled"
    sub.disabled_at = datetime.now(timezone.utc)
    sub.disabled_reason = "operator_disabled"
    session.flush()
    return DisableSubscriptionResponse(
        subscription_id=sub.id, status=sub.status
    )


@router.get("/subscriptions", response_model=SubscriptionStatusResponse)
def list_subscriptions(
    session: Session = Depends(get_session),
) -> SubscriptionStatusResponse:
    """List all registered push subscriptions with status counts."""
    all_subs = session.execute(
        select(PushSubscription).order_by(PushSubscription.created_at.desc())
    ).scalars().all()

    active_count = 0
    disabled_count = 0
    views: list[SubscriptionView] = []

    for sub in all_subs:
        if sub.status == "active":
            active_count += 1
        elif sub.status == "disabled":
            disabled_count += 1
        views.append(
            SubscriptionView(
                subscription_id=sub.id,
                endpoint=sub.endpoint,
                status=sub.status,
                created_at=sub.created_at,
                disabled_at=sub.disabled_at,
                disabled_reason=sub.disabled_reason,
            )
        )

    return SubscriptionStatusResponse(
        active_count=active_count,
        disabled_count=disabled_count,
        subscriptions=views,
    )
