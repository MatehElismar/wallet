"""Deterministic validation of frontend configuration and assets."""

from __future__ import annotations

import json
import re
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


def _read_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


class TestFrontendConfig:
    def test_package_json(self) -> None:
        pkg = _read_json(WEB_ROOT / "package.json")
        assert pkg["private"] is True
        assert "next" in (pkg.get("dependencies") or {})
        assert "react" in (pkg.get("dependencies") or {})
        assert "react-dom" in (pkg.get("dependencies") or {})
        scripts = pkg.get("scripts") or {}
        assert "dev" in scripts
        assert "build" in scripts
        assert "start" in scripts

    def test_tsconfig(self) -> None:
        import json
        tsconfig = _read_json(WEB_ROOT / "tsconfig.json")
        compiler = tsconfig.get("compilerOptions") or {}
        assert compiler.get("jsx") == "preserve"
        assert compiler.get("strict") is True

    def test_next_config(self) -> None:
        config_path = WEB_ROOT / "next.config.js"
        config_text = config_path.read_text()
        assert "output" in config_text
        assert '"standalone"' in config_text or "'standalone'" in config_text

    def test_manifest_json(self) -> None:
        manifest = _read_json(WEB_ROOT / "public" / "manifest.json")
        assert manifest.get("name")
        assert manifest.get("short_name")
        assert manifest.get("start_url") == "/"
        assert manifest.get("display") == "standalone"
        assert isinstance(manifest.get("icons"), list)
        assert len(manifest["icons"]) >= 2

    def test_service_worker(self) -> None:
        sw_path = WEB_ROOT / "public" / "sw.js"
        sw_text = sw_path.read_text()
        assert "self.addEventListener" in sw_text
        assert '"install"' in sw_text or "'install'" in sw_text
        assert '"fetch"' in sw_text or "'fetch'" in sw_text

    def test_env_example(self) -> None:
        env_path = WEB_ROOT / ".env.example"
        assert env_path.exists()
        env_text = env_path.read_text()
        assert "WALLET_V2_API_URL" in env_text
        assert "NEXT_PUBLIC_API_BASE_URL" not in env_text

    def test_api_lib(self) -> None:
        api_path = WEB_ROOT / "src" / "lib" / "api.ts"
        api_text = api_path.read_text()
        assert "NEXT_PUBLIC_API_BASE_URL" not in api_text
        assert '"/api"' in api_text or "'/api'" in api_text
        assert "export async function listBatches" in api_text
        assert "export async function getBatchDetail" in api_text
        assert "export async function resolveLine" in api_text
        assert "export async function mapAccount" in api_text
        assert "export async function approveBatch" in api_text
        assert "export async function dryRunImport" in api_text

    def test_app_pages_exist(self) -> None:
        assert (WEB_ROOT / "src" / "app" / "layout.tsx").exists()
        assert (WEB_ROOT / "src" / "app" / "page.tsx").exists()
        assert (WEB_ROOT / "src" / "app" / "batches" / "[id]" / "page.tsx").exists()

    def test_api_base_url_is_not_hardcoded(self) -> None:
        api_path = WEB_ROOT / "src" / "lib" / "api.ts"
        config_path = WEB_ROOT / "next.config.js"
        texts = [api_path.read_text(), config_path.read_text()]
        for text in texts:
            assert "wallet_v2" not in text, "database credentials must not appear in frontend code"
            assert "DATABASE_URL" not in text, "database credentials must not appear in frontend code"
            assert "API_KEY" not in text, "API keys must not appear in frontend code"
            assert "api_key" not in text, "API keys must not appear in frontend code"
            assert "PSQL" not in text, "database connection must not appear in frontend code"
            assert "NEXT_PUBLIC_API_BASE_URL" not in text, "NEXT_PUBLIC_ must not appear in frontend code"
            assert "NEXT_PUBLIC" not in text, "NEXT_PUBLIC_ vars must not appear in frontend code"

    def test_apphosting_yaml(self) -> None:
        ah_path = WEB_ROOT / "apphosting.yaml"
        assert ah_path.exists()
        ah_text = ah_path.read_text()
        assert "WALLET_V2_API_URL" in ah_text
        assert "NEXT_PUBLIC_API_BASE_URL" not in ah_text
        assert not re.search(r'(?i)database.*url', ah_text), "database URL must not appear in apphosting config"
        assert not re.search(r'(?i)api.?key', ah_text), "API key must not appear in apphosting config"

    def test_docs_exist(self) -> None:
        docs_path = Path(__file__).resolve().parent.parent / "docs" / "deployment.md"
        assert docs_path.exists()
        docs_text = docs_path.read_text()
        assert "unauthenticated" in docs_text.lower()
        assert "DRY_RUN" in docs_text or "dry_run" in docs_text or "dry-run" in docs_text
        assert "WALLET_V2_API_URL" in docs_text
        assert "WALLET_V2__DATABASE__URL" in docs_text

    def test_service_worker_registration_in_layout(self) -> None:
        layout_path = WEB_ROOT / "src" / "app" / "layout.tsx"
        layout_text = layout_path.read_text()
        assert "serviceWorker" in layout_text
        assert "navigator.serviceWorker.register" in layout_text
        assert '"/sw.js"' in layout_text or "'/sw.js'" in layout_text

    def test_api_proxy_route_exists(self) -> None:
        proxy_route = WEB_ROOT / "src" / "app" / "api" / "[...path]" / "route.ts"
        assert proxy_route.exists(), "Next.js API proxy route must exist"
        proxy_text = proxy_route.read_text()
        assert "WALLET_V2_API_URL" in proxy_text
        assert "NEXT_PUBLIC" not in proxy_text
        assert "proxyRequest" in proxy_text

    def test_manifest_paths_preserved(self) -> None:
        manifest = _read_json(WEB_ROOT / "public" / "manifest.json")
        icons = manifest.get("icons", [])
        assert any(icon.get("src") == "/icon-192.png" for icon in icons)
        assert any(icon.get("src") == "/icon-512.png" for icon in icons)
        assert manifest.get("start_url") == "/"

    def test_no_literal_placeholder_endpoint(self) -> None:
        ah_path = WEB_ROOT / "apphosting.yaml"
        ah_text = ah_path.read_text()
        assert "WALLET_V2_API_URL" in ah_text
        assert "http://placeholder" not in ah_text
        assert "http://example.com" not in ah_text
        assert "https://example.com" not in ah_text

    def test_no_next_public_anywhere_in_web_src(self) -> None:
        import os
        src_root = WEB_ROOT / "src"
        for dirpath, _dirnames, filenames in os.walk(src_root):
            for fn in filenames:
                if fn.endswith((".ts", ".tsx", ".js", ".jsx")):
                    text = (Path(dirpath) / fn).read_text()
                    assert "NEXT_PUBLIC" not in text, f"NEXT_PUBLIC_ found in {dirpath}/{fn}"
