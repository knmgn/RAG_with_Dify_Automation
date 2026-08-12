#!/usr/bin/env python3
"""Phase 5 — end-to-end test of the published Chatflow.

Drives the bot through Dify's public Service API (the same path a real
integration would use, not the console debugger) and checks the three
behaviours the demo depends on:

  1. 規程Q&A       — a policy question is answered from the knowledge base,
                     with the amount quoted verbatim and a citation.
  2. ガードレール    — an out-of-scope question is refused with the fixed
                     deflection message instead of an invented answer.
  3. ファイル要求    — a template request routes through the n8n webhook and the
                     returned download URL actually serves the xlsx.

    python3 scripts/test_e2e.py

Complements docker/test/test_webhook.sh, which covers the n8n half on its own.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dify_console import REPO_ROOT, DifyConsole, connect, load_env

STATE_FILE = REPO_ROOT / "scripts" / ".provision_state.json"
API_KEY_NAME = "e2e-test"

PASS = "\033[0;32m[PASS]\033[0m"
FAIL = "\033[0;31m[FAIL]\033[0m"
INFO = "\033[0;36m[INFO]\033[0m"


def get_api_key(console: DifyConsole, app_id: str) -> str:
    """Reuse an existing Service API key for the app, or mint one."""
    existing = console.get(f"/apps/{app_id}/api-keys").get("data", [])
    if existing:
        return existing[0]["token"]
    return console.post(f"/apps/{app_id}/api-keys", {})["token"]


def ask(base_url: str, api_key: str, query: str, user: str = "e2e-test") -> dict[str, Any]:
    payload = json.dumps(
        {"inputs": {}, "query": query, "response_mode": "blocking", "user": user},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/v1/chat-messages",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"[FAIL] chat request failed: HTTP {exc.code}\n{exc.read().decode('utf-8', 'replace')}")


def download(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def main() -> int:
    if not STATE_FILE.exists():
        raise SystemExit("[FAIL] scripts/.provision_state.json not found. Run the provisioning scripts first.")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    app_id = state.get("app_id")
    if not app_id:
        raise SystemExit("[FAIL] no app_id in state. Run provision_chatflow.py first.")

    env = load_env()
    base_url = env.get("DIFY_BASE_URL", "http://localhost").rstrip("/")
    console = connect(env)
    api_key = get_api_key(console, app_id)

    print("=" * 72)
    print("  Demo-Logi-Bot  —  end-to-end test (Dify Service API)")
    print(f"  app_id: {app_id}")
    print("=" * 72)
    print()

    failures = 0

    # ── 1. 規程Q&A ──────────────────────────────────────────────────────
    print(f"{INFO} Test 1/3: 規程Q&A — 「深夜帰りのタクシー代いくら？」")
    answer = ask(base_url, api_key, "深夜帰りのタクシー代いくら？").get("answer", "")
    checks = {
        "quotes the cap verbatim (15,000円)": "15,000円" in answer,
        "cites the regulation number": "DL-HR-RG-2024-007" in answer,
        "uses the 3-block format": "【結論】" in answer and "【引用元】" in answer,
        "did not fall back to the deflection message": "見当たりませんでした" not in answer,
    }
    for label, ok in checks.items():
        print(f"       {'✓' if ok else '✗'} {label}")
    if all(checks.values()):
        print(f"{PASS} policy question answered from the knowledge base")
    else:
        failures += 1
        print(f"{FAIL} unexpected answer:\n{answer[:600]}")
    print()

    # ── 2. ガードレール ──────────────────────────────────────────────────
    print(f"{INFO} Test 2/3: ガードレール — 「猫を飼ったら手当出る？」")
    answer = ask(base_url, api_key, "猫を飼ったら手当出る？").get("answer", "")
    checks = {
        "refuses instead of inventing": "見当たりませんでした" in answer,
        "names the responsible contact (総務部の佐藤)": "佐藤" in answer,
        "gives the extension (内線1234)": "1234" in answer,
    }
    for label, ok in checks.items():
        print(f"       {'✓' if ok else '✗'} {label}")
    if all(checks.values()):
        print(f"{PASS} out-of-scope question deflected, no hallucination")
    else:
        failures += 1
        print(f"{FAIL} unexpected answer:\n{answer[:600]}")
    print()

    # ── 3. ファイル要求 → n8n → ダウンロード ─────────────────────────────
    print(f"{INFO} Test 3/3: ファイル要求 — 「経費精算のフォーマットちょうだい」")
    answer = ask(base_url, api_key, "経費精算のフォーマットちょうだい").get("answer", "")
    download_url = "http://localhost:5678/webhook/files/expense-v3"
    checks = {
        "routed to the n8n branch (filename returned)": "経費精算テンプレート_v3.xlsx" in answer,
        "returned the localhost download URL": download_url in answer,
        "included the deadline from n8n": "25日" in answer,
    }
    for label, ok in checks.items():
        print(f"       {'✓' if ok else '✗'} {label}")

    if download_url in answer:
        status, body = download(download_url)
        is_xlsx = body[:2] == b"PK" and len(body) > 1000
        print(f"       {'✓' if is_xlsx else '✗'} download URL serves a real xlsx "
              f"(HTTP {status}, {len(body)} bytes)")
        checks["download works"] = is_xlsx

    if all(checks.values()):
        print(f"{PASS} file request routed through n8n and the file downloads")
    else:
        failures += 1
        print(f"{FAIL} unexpected answer:\n{answer[:600]}")
    print()

    print("=" * 72)
    if failures:
        print(f"  {failures} of 3 tests FAILED")
    else:
        print("  All 3 end-to-end tests passed.")
        print("  The full chain works: Dify → Knowledge / n8n → browser download.")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
