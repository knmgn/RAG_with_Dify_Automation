#!/usr/bin/env python3
"""Phase 4 — build the Dify Chatflow from code.

Generates the DSL for the Demo-Logi-Bot Chatflow described in
`02_dify_chatflow_design.md` §2 and §4-7, imports it, publishes it, and writes
the exported DSL to `dify/chatflow_dsl.yaml` as the §7 deliverable.

    python3 scripts/provision_chatflow.py

Requires provision_knowledge.py to have run first (it needs the dataset id).

Graph:

    [Start] → [Intent classifier] ─ Policy Q&A ──→ [Knowledge retrieval] → [Answer generation] → [Answer]
                                  └ File request → [n8n Webhook] → [Parse response] → [File answer]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from dify_console import REPO_ROOT, DifyConsole, connect, load_env

# Retrieval settings live with the knowledge provisioning so the two cannot drift.
from provision_knowledge import RETRIEVAL_WEIGHTS, SCORE_THRESHOLD, TOP_K

STATE_FILE = REPO_ROOT / "scripts" / ".provision_state.json"
DSL_OUTPUT = REPO_ROOT / "dify" / "chatflow_dsl.yaml"

APP_NAME = "Demo-Logi-Bot (Internal Policy Assistant)"
APP_DESCRIPTION = (
    "Answers Demo Logistics Inc. policy questions and delivers the expense report "
    "template. Policy Q&A uses Hybrid Search with Weighted Score; file requests go "
    "through an n8n webhook."
)

LLM_PROVIDER = "langgenius/openai/openai"
LLM_MODEL = "gpt-4o-mini"

CLASS_QA = "1"
CLASS_FILE = "2"

# §1-2 verbatim, with one required fix: the context placeholder Dify actually
# substitutes is `{{#context#}}` (graphon/nodes/llm/llm_utils.py:CONTEXT_PLACEHOLDER).
# The design doc's `{{#context.result#}}` is never replaced, so the model would
# receive the literal string and answer with no knowledge at all.
SYSTEM_PROMPT = """# Role
You are "Demo-Logi-Bot", the internal policy assistant for Demo Logistics Inc.
You answer employee questions about travel, expenses and HR procedures accurately, based on the internal policy (DL-HR-RG-2024-007).

# Non-negotiable rules
1. Always base your answer on the knowledge inside the <context> tag (the policy text).
2. If <context> does not contain the answer, or its relevance is low, NEVER fill the gap with guesses, assumptions or general knowledge. Instead, reply with exactly this message:

   "No explicit provision covering your question was found in the internal policy (DL-HR-RG-2024-007). Please contact People Operations directly (ext. 1234 / people-ops@demo-logistics.example.com)."

3. Even when asked about general legal, tax or employment matters, use the message above unless the internal policy addresses the point directly. General explanations such as "Under the FLSA..." or "The IRS generally..." are prohibited.
4. Quote amounts, deadlines and conditions from <context> exactly as written, without rewording (e.g. write "USD 100 per ride (tax and tip included)" word for word).
5. If the user asks for an exception or a change to the rules (e.g. "Can you make an exception for me?"), state that you have no authority to decide and direct them to People Operations.

# Answer format (mandatory)
Structure every answer in these three blocks:

**Answer**
(A direct answer in 1-3 sentences. List any amounts, conditions and deadlines as bullet points.)

**Details**
(Supporting explanation based on the relevant article. Always mention prohibited cases or exceptions if there are any.)

**Source**
- Policy: Demo Logistics Inc. Travel, Expense Reimbursement and HR Procedures Policy (DL-HR-RG-2024-007)
- Section: Article X, Clause/Paragraph X (topic)
- Last revised: October 1, 2024 (Revision 3)

# Tone and style
- Polite, concise business English.
- No unnecessary preamble (such as "Thank you for your question").
- No emoji.

# Prohibited
- Amounts, deadlines, names or departments that are not grounded in the knowledge
- Reusing earlier answers instead of consulting the knowledge each time
- Hedging language such as "probably", "generally" or "I think"
- Inventing policy numbers or article numbers

# Input
User question: {{#sys.query#}}

Reference knowledge:
<context>
{{#context#}}
</context>"""

# §2-2 verbatim.
CLASSIFIER_INSTRUCTION = """Classify the user's message into one of the following two classes.

[Class 1: Policy Q&A]
- Questions about what the policy says
- Examples: "What is the cap for a late-night ride home?", "When is the expense report deadline?", "How is the night shift differential calculated?"

[Class 2: File request]
- Requests to send or download the expense report template or form
- Examples: "Send me the expense report template", "I need the template link", "Can you send me the Excel file?"

If the classification is ambiguous, choose [Class 1: Policy Q&A]."""

# The HTTP Request node exposes its response body as a *string*
# (`outputs["body"] = response.text`), not as a parsed object. So neither
# `{{#n8n_webhook.body.message#}}` nor the design doc's
# `{{#http_request.response.message#}}` resolves to anything — the Answer node
# just renders empty. A Code node in between turns the JSON into real
# variables. It runs in Dify's local sandbox container, so this adds no
# external dependency.
PARSE_RESPONSE_CODE = '''import json


def main(body: str) -> dict:
    """Turn Workflow 1's JSON response into named workflow variables."""
    data = json.loads(body) if body else {}
    keys = ("message", "filename", "download_url", "deadline", "macro_warning", "regulation_ref")
    return {key: str(data.get(key, "")) for key in keys}
'''

PARSE_RESPONSE_OUTPUTS = {
    "message": {"type": "string"},
    "filename": {"type": "string"},
    "download_url": {"type": "string"},
    "deadline": {"type": "string"},
    "macro_warning": {"type": "string"},
    "regulation_ref": {"type": "string"},
}

# §4-7 ⑤ — renders the JSON that Workflow 1 returns into a user-facing message.
FILE_ANSWER_TEMPLATE = """{{#parse_response.message#}}

📎 **{{#parse_response.filename#}}**
{{#parse_response.download_url#}}

**Please note**
- Deadline: {{#parse_response.deadline#}}
- {{#parse_response.macro_warning#}}

**Source**
Policy: {{#parse_response.regulation_ref#}}
Contacts: People Operations (ext. 1234) / Accounts Payable (ext. 1456)"""

OPENING_STATEMENT = (
    "Hi, I'm Demo-Logi-Bot, the internal policy assistant for Demo Logistics Inc. "
    "Ask me about travel, expense reimbursement and HR procedures."
)

SUGGESTED_QUESTIONS = [
    "How much can I claim for a late-night ride home?",
    "When is the expense report deadline?",
    "Send me the expense report template.",
]


def log(message: str) -> None:
    print(message, flush=True)


def read_n8n_token_from_container() -> str:
    """Pull the X-Auth-Token value out of the n8n Header Auth credential.

    Saves having to copy the shared secret into two places by hand. Only used
    when N8N_WEBHOOK_TOKEN is not set in scripts/.dify_admin.env.
    """
    script = (
        "n8n export:credentials --decrypted --all --output=/tmp/creds.json >/dev/null 2>&1; "
        'node -e "const d=require(\\"/tmp/creds.json\\");'
        'for(const c of d) if(c.type===\\"httpHeaderAuth\\") process.stdout.write(c.data.value);"; '
        "rm -f /tmp/creds.json"
    )
    result = subprocess.run(
        ["docker", "exec", "n8n_local", "sh", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    token = result.stdout.strip()
    if not token:
        raise SystemExit(
            "[FAIL] could not read the n8n webhook token.\n"
            "       Set N8N_WEBHOOK_TOKEN in scripts/.dify_admin.env, or make sure the\n"
            "       n8n_local container is running with a Header Auth credential."
        )
    return token


def node(node_id: str, position: tuple[int, int], data: dict[str, Any]) -> dict[str, Any]:
    x, y = position
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "width": 244,
        "height": 120,
        "sourcePosition": "right",
        "targetPosition": "left",
        "selected": False,
        "data": {"desc": "", "selected": False, **data},
    }


def edge(source: str, target: str, source_type: str, target_type: str, handle: str = "source") -> dict[str, Any]:
    return {
        "id": f"{source}-{handle}-{target}-target",
        "source": source,
        "sourceHandle": handle,
        "target": target,
        "targetHandle": "target",
        "type": "custom",
        "zIndex": 0,
        "data": {
            "sourceType": source_type,
            "targetType": target_type,
            "isInIteration": False,
            "isInLoop": False,
        },
    }


def build_dsl(dataset_id: str, webhook_url: str, webhook_token: str) -> dict[str, Any]:
    model_config = {
        "provider": LLM_PROVIDER,
        "name": LLM_MODEL,
        "mode": "chat",
        # Deterministic on purpose: this bot quotes amounts and deadlines verbatim.
        "completion_params": {"temperature": 0},
    }

    request_body = json.dumps(
        {
            "intent": "request_expense_template",
            "user_id": "{{#sys.user_id#}}",
            "user_query": "{{#sys.query#}}",
            "conversation_id": "{{#sys.conversation_id#}}",
            # §4-1 says sys.current_time, which does not exist in Dify.
            # The system variable is sys.timestamp.
            "requested_at": "{{#sys.timestamp#}}",
            "metadata": {"source": "dify-chatflow", "template_key": "expense_template_v3"},
        },
        ensure_ascii=False,
        indent=2,
    )

    nodes = [
        node("start", (30, 300), {"type": "start", "title": "Start", "variables": []}),
        node(
            "intent_classifier",
            (330, 300),
            {
                "type": "question-classifier",
                "title": "Intent classifier",
                "query_variable_selector": ["sys", "query"],
                "model": model_config,
                "classes": [
                    {"id": CLASS_QA, "name": "Policy Q&A"},
                    {"id": CLASS_FILE, "name": "File request"},
                ],
                "instruction": CLASSIFIER_INSTRUCTION,
                "vision": {"enabled": False},
            },
        ),
        node(
            "kb_retrieval",
            (650, 180),
            {
                "type": "knowledge-retrieval",
                "title": "Knowledge retrieval",
                "query_variable_selector": ["sys", "query"],
                "dataset_ids": [dataset_id],
                "retrieval_mode": "multiple",
                "multiple_retrieval_config": {
                    "top_k": TOP_K,
                    "score_threshold": SCORE_THRESHOLD,
                    "reranking_enable": False,
                    "reranking_mode": "weighted_score",
                    "weights": RETRIEVAL_WEIGHTS,
                },
                "metadata_filtering_mode": "disabled",
                "vision": {"enabled": False},
            },
        ),
        node(
            "llm_answerer",
            (960, 180),
            {
                "type": "llm",
                "title": "Answer generation",
                "model": model_config,
                "prompt_template": [
                    {"role": "system", "text": SYSTEM_PROMPT, "edition_type": "basic"},
                    {"role": "user", "text": "{{#sys.query#}}", "edition_type": "basic"},
                ],
                "context": {"enabled": True, "variable_selector": ["kb_retrieval", "result"]},
                "prompt_config": {"jinja2_variables": []},
                "vision": {"enabled": False},
            },
        ),
        node(
            "final_answer",
            (1270, 180),
            {"type": "answer", "title": "Answer", "answer": "{{#llm_answerer.text#}}"},
        ),
        node(
            "n8n_webhook",
            (650, 470),
            {
                "type": "http-request",
                "title": "n8n Webhook",
                "method": "post",
                "url": webhook_url,
                "authorization": {"type": "no-auth", "config": None},
                # Shared secret comes from the env var, never inlined here, so the
                # exported DSL can be committed.
                "headers": "Content-Type:application/json\nX-Auth-Token:{{#env.N8N_WEBHOOK_TOKEN#}}",
                "params": "",
                "body": {"type": "json", "data": [{"key": "", "type": "text", "value": request_body}]},
                "timeout": {"connect": 10, "read": 10, "write": 10},
                # §4-1: 2 retries.
                "retry_config": {"retry_enabled": True, "max_retries": 2, "retry_interval": 1000},
                "ssl_verify": False,
            },
        ),
        node(
            "parse_response",
            (960, 470),
            {
                "type": "code",
                "title": "Parse response",
                "code_language": "python3",
                "code": PARSE_RESPONSE_CODE,
                "variables": [{"variable": "body", "value_selector": ["n8n_webhook", "body"]}],
                "outputs": PARSE_RESPONSE_OUTPUTS,
            },
        ),
        node(
            "file_answer",
            (1270, 470),
            {"type": "answer", "title": "File answer", "answer": FILE_ANSWER_TEMPLATE},
        ),
    ]

    edges = [
        edge("start", "intent_classifier", "start", "question-classifier"),
        edge("intent_classifier", "kb_retrieval", "question-classifier", "knowledge-retrieval", CLASS_QA),
        edge("intent_classifier", "n8n_webhook", "question-classifier", "http-request", CLASS_FILE),
        edge("kb_retrieval", "llm_answerer", "knowledge-retrieval", "llm"),
        edge("llm_answerer", "final_answer", "llm", "answer"),
        edge("n8n_webhook", "parse_response", "http-request", "code"),
        edge("parse_response", "file_answer", "code", "answer"),
    ]

    return {
        "app": {
            "name": APP_NAME,
            "description": APP_DESCRIPTION,
            "mode": "advanced-chat",
            "icon_type": "emoji",
            "icon": "🚚",
            "icon_background": "#FFEAD5",
            "use_icon_as_answer_icon": False,
        },
        "kind": "app",
        "version": "0.6.0",
        "workflow": {
            "environment_variables": [
                {
                    "id": str(uuid.uuid4()),
                    "name": "N8N_WEBHOOK_TOKEN",
                    "value": webhook_token,
                    "value_type": "secret",
                    "selector": ["env", "N8N_WEBHOOK_TOKEN"],
                    "description": "Shared secret for the n8n webhook Header Auth credential.",
                }
            ],
            "conversation_variables": [],
            "features": {
                "opening_statement": OPENING_STATEMENT,
                "suggested_questions": SUGGESTED_QUESTIONS,
                "suggested_questions_after_answer": {"enabled": False},
                "retriever_resource": {"enabled": True},
                "sensitive_word_avoidance": {"enabled": False},
                "speech_to_text": {"enabled": False},
                "text_to_speech": {"enabled": False},
                "file_upload": {"enabled": False, "allowed_file_types": [], "number_limits": 0},
            },
            "graph": {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.7}},
        },
    }


def find_app(console: DifyConsole, name: str) -> dict[str, Any] | None:
    response = console.get("/apps?page=1&limit=100")
    for app in response.get("data", []):
        if app.get("name") == name:
            return app
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recreate", action="store_true", help="delete an existing app of the same name first")
    args = parser.parse_args()

    if not STATE_FILE.exists():
        raise SystemExit("[FAIL] scripts/.provision_state.json not found. Run provision_knowledge.py first.")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    dataset_id = state["dataset_id"]

    env = load_env()
    token = env.get("N8N_WEBHOOK_TOKEN") or read_n8n_token_from_container()
    path = env.get("N8N_INTENT_DISPATCHER_PATH", "").strip("/")
    if not path:
        raise SystemExit("[FAIL] N8N_INTENT_DISPATCHER_PATH is not set in scripts/.dify_admin.env")
    # §4-7 "two URLs" design: Dify reaches n8n by its Docker service name, never localhost.
    webhook_url = f"http://n8n_local:5678/webhook/{path}"

    console = connect(env)
    log("[ok]   authenticated")
    log(f"[info] dataset  : {dataset_id}")
    log(f"[info] webhook  : {webhook_url}")

    existing = find_app(console, APP_NAME)
    if existing:
        if not args.recreate:
            raise SystemExit(
                f"[FAIL] app '{APP_NAME}' already exists (id={existing['id']}).\n"
                "       Re-run with --recreate to replace it."
            )
        console.delete(f"/apps/{existing['id']}")
        log(f"[ok]   deleted existing app {existing['id']}")

    dsl = build_dsl(dataset_id, webhook_url, token)
    # JSON is valid YAML, so the importer accepts it directly and we avoid a
    # PyYAML dependency. The canonical YAML comes back from the export below.
    result = console.post(
        "/apps/imports",
        {"mode": "yaml-content", "yaml_content": json.dumps(dsl, ensure_ascii=False)},
    )
    if result.get("status") not in ("completed", "completed-with-warnings"):
        raise SystemExit(f"[FAIL] DSL import failed: {json.dumps(result, ensure_ascii=False, indent=2)}")
    app_id = result["app_id"]
    log(f"[ok]   app imported (id={app_id}) status={result.get('status')}")

    console.post(f"/apps/{app_id}/workflows/publish", {})
    log("[ok]   workflow published")

    exported = console.get(f"/apps/{app_id}/export?include_secret=false")
    DSL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DSL_OUTPUT.write_text(exported["data"], encoding="utf-8")
    log(f"[ok]   DSL exported to {DSL_OUTPUT.relative_to(REPO_ROOT)} (secrets excluded)")

    # /apps/{id}/site is POST-only; the webapp access token comes with app detail.
    access_token = (console.get(f"/apps/{app_id}") or {}).get("site", {}).get("access_token", "")

    STATE_FILE.write_text(
        json.dumps({**state, "app_id": app_id, "app_name": APP_NAME}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    base = env.get("DIFY_BASE_URL", "http://localhost").rstrip("/")
    log("")
    log("=" * 60)
    log(f"  Chatflow ready: {APP_NAME}")
    log(f"  app_id : {app_id}")
    log(f"  editor : {base}/app/{app_id}/workflow")
    if access_token:
        log(f"  chat   : {base}/chat/{access_token}")
    log("=" * 60)
    log("  Next: python3 scripts/test_e2e.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
