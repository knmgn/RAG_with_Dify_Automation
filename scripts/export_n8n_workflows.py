#!/usr/bin/env python3
"""Export the two n8n workflows to docker/n8n/workflows/ as committable JSON.

`n8n export:workflow` output cannot be committed as-is to a public repo: its
`shared` block carries the owner's **email address** and internal project IDs.
This script keeps only the fields n8n needs on import and drops everything that
is instance-specific or personal.

    python3 scripts/export_n8n_workflows.py

Credential *references* (`{"httpHeaderAuth": {"id", "name"}}`) are kept — they
contain no secret, and keeping them means the Header Auth credential re-links
by name on import instead of silently ending up unauthenticated.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from dify_console import REPO_ROOT

OUTPUT_DIR = REPO_ROOT / "docker" / "n8n" / "workflows"
CONTAINER = "n8n_local"

WORKFLOWS = [
    ("AXXNDl9AWuMY11w1", "workflow_1_intent_dispatcher.json"),
    ("uzYO1oFIih6QVHNn", "workflow_2_file_server.json"),
]

# Everything else in the raw export is instance state (ids, timestamps,
# version counters) or personal data (`shared` → owner name and email).
KEEP_TOP_LEVEL = ("name", "nodes", "connections", "settings", "pinData")


def export_raw(workflow_id: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "n8n", "export:workflow", f"--id={workflow_id}"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    # The CLI prints telemetry notices before the JSON, so start at the first brace.
    start = result.stdout.find("[")
    if start == -1:
        raise SystemExit(f"[FAIL] could not export {workflow_id}\n{result.stdout}\n{result.stderr}")
    payload = json.loads(result.stdout[start:])
    return payload[0] if isinstance(payload, list) else payload


def sanitize(workflow: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: workflow[key] for key in KEEP_TOP_LEVEL if key in workflow}
    cleaned.setdefault("pinData", {})
    return cleaned


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for workflow_id, filename in WORKFLOWS:
        cleaned = sanitize(export_raw(workflow_id))

        blob = json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True)
        # Cheap guard against ever re-introducing personal data by accident.
        for marker in ("@", "projectId", "shared"):
            if marker in blob and marker != "@":
                raise SystemExit(f"[FAIL] '{marker}' survived sanitization in {filename}")
        if "@" in blob:
            suspicious = [line.strip() for line in blob.splitlines() if "@" in line]
            raise SystemExit(f"[FAIL] possible email address in {filename}: {suspicious[:3]}")

        (OUTPUT_DIR / filename).write_text(blob + "\n", encoding="utf-8")
        node_count = len(cleaned.get("nodes", []))
        print(f"[ok]   {filename}  ({cleaned['name']}, {node_count} nodes)")

    print(f"\nWrote to {OUTPUT_DIR.relative_to(REPO_ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
