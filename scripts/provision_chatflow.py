#!/usr/bin/env python3
"""Phase 4 — build the Dify Chatflow from code.

Generates the DSL for the Demo-Logi-Bot Chatflow described in
`02_dify_chatflow_design.md` §2 and §4-7, imports it, publishes it, and writes
the exported DSL to `dify/chatflow_dsl.yaml` as the §7 deliverable.

    python3 scripts/provision_chatflow.py

Requires provision_knowledge.py to have run first (it needs the dataset id).

Graph:

    [開始] → [インテント分類] ─ 規程Q&A ──→ [ナレッジ検索] → [回答生成] → [回答]
                             └ ファイル要求 → [n8n Webhook] → [ファイル回答]
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

APP_NAME = "Demo-Logi-Bot（社内規程アシスタント）"
APP_DESCRIPTION = (
    "株式会社デモ・ロジスティクスの社内規程 Q&A と経費精算テンプレート配布を行う "
    "Chatflow。規程Q&Aは Hybrid Search + Rerank、ファイル要求は n8n Webhook 経由。"
)

LLM_PROVIDER = "langgenius/openai/openai"
LLM_MODEL = "gpt-4o-mini"

CLASS_QA = "1"
CLASS_FILE = "2"

# §1-2 verbatim, with one required fix: the context placeholder Dify actually
# substitutes is `{{#context#}}` (graphon/nodes/llm/llm_utils.py:CONTEXT_PLACEHOLDER).
# The design doc's `{{#context.result#}}` is never replaced, so the model would
# receive the literal string and answer with no knowledge at all.
SYSTEM_PROMPT = """# 役割
あなたは「株式会社デモ・ロジスティクス」社内規程アシスタント "Demo-Logi-Bot" です。
社員の旅費交通費・経費精算・労務に関する質問に、社内規程（DL-HR-RG-2024-007）に基づいて正確に回答します。

# 絶対遵守ルール
1. 回答は必ず<context>タグ内のナレッジ（マニュアル本文）を最優先で参照してください。
2. <context>に該当する記載が存在しない、または関連スコアが低い場合は、推測・憶測・一般論で補完してはいけません。代わりに必ず以下の定型文で回答してください：

   「ご質問の件について、社内規程（DL-HR-RG-2024-007）内に明示的な記載が見当たりませんでした。詳細については総務部の佐藤（内線1234／sato.kenichi@demo-logistics.example.co.jp）まで直接お問い合わせください。」

3. 法律・税務・労務に関する一般論を質問された場合でも、社内規程に直接の記載がない限り、上記の定型文で回答してください。「労働基準法では〜」等の一般解説は禁止です。
4. 金額・期日・条件は、<context>の表記を一字一句改変せず引用してください（例：「1回あたり15,000円（消費税込）」と完全一致で書く）。
5. ユーザーが規程の改変・例外適用を求めた場合（「特別に認めて」等）は、判断権限がないため総務部に確認するよう促してください。

# 回答フォーマット（厳守）
回答は以下の3ブロック構造で出力してください。

【結論】
（質問への直接回答を1〜3文で簡潔に。金額・条件・期日があれば箇条書きで明示）

【詳細・補足】
（規程の該当条文を踏まえて補足説明。NG事例や例外条件がある場合は必ず明記）

【引用元】
- 規程名：株式会社デモ・ロジスティクス 旅費交通費・経費精算および労務手続き規定（DL-HR-RG-2024-007）
- 該当箇所：第◯章 第◯条 第◯項（◯◯について）
- 最終改訂：2024年10月1日（第3版）

# トーン・スタイル
- 敬体（です・ます調）で、ビジネス文書として丁寧かつ簡潔に。
- 不必要な前置き（「ご質問ありがとうございます」等）は省略。
- 絵文字は使用しない。

# 禁止事項
- ナレッジに根拠のない金額・期限・人名・部署名の生成
- 過去の質問履歴に基づく回答の使い回し（毎回ナレッジを参照する）
- "おそらく"、"一般的には"、"だと思います" 等の曖昧表現
- 規程番号・条文番号の創作

# 入力データ
ユーザーの質問：{{#sys.query#}}

参照ナレッジ：
<context>
{{#context#}}
</context>"""

# §2-2 verbatim.
CLASSIFIER_INSTRUCTION = """ユーザーの発話を以下の2クラスのいずれかに分類してください。

【クラス1：規程Q&A】
- 規程内容に関する質問
- 例：「タクシー代の上限は？」「経費精算の締切は？」「夜勤手当の計算方法は？」

【クラス2：ファイル要求】
- 経費精算テンプレートやフォーマットの送付・ダウンロード要求
- 例：「経費精算のフォーマットちょうだい」「テンプレートのリンクが欲しい」「Excelファイル送って」

判定が曖昧な場合は【クラス1：規程Q&A】を選択してください。"""

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

【ご注意】
- 提出期限：{{#parse_response.deadline#}}
- {{#parse_response.macro_warning#}}

【引用元】
規程：{{#parse_response.regulation_ref#}}
窓口：総務部 佐藤（内線1234）／ 経理部 鈴木（内線1456）"""

OPENING_STATEMENT = (
    "株式会社デモ・ロジスティクスの社内規程アシスタントです。"
    "旅費交通費・経費精算・労務手続きについてお答えします。"
)

SUGGESTED_QUESTIONS = [
    "深夜帰りのタクシー代いくら？",
    "経費精算の締め切りはいつ？",
    "経費精算のフォーマットちょうだい",
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
        node("start", (30, 300), {"type": "start", "title": "開始", "variables": []}),
        node(
            "intent_classifier",
            (330, 300),
            {
                "type": "question-classifier",
                "title": "インテント分類",
                "query_variable_selector": ["sys", "query"],
                "model": model_config,
                "classes": [
                    {"id": CLASS_QA, "name": "規程Q&A"},
                    {"id": CLASS_FILE, "name": "ファイル要求"},
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
                "title": "ナレッジ検索",
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
                "title": "回答生成",
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
            {"type": "answer", "title": "回答", "answer": "{{#llm_answerer.text#}}"},
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
                "title": "レスポンス解析",
                "code_language": "python3",
                "code": PARSE_RESPONSE_CODE,
                "variables": [{"variable": "body", "value_selector": ["n8n_webhook", "body"]}],
                "outputs": PARSE_RESPONSE_OUTPUTS,
            },
        ),
        node(
            "file_answer",
            (1270, 470),
            {"type": "answer", "title": "ファイル回答", "answer": FILE_ANSWER_TEMPLATE},
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
    # §4-7 "URLの二刀流": Dify reaches n8n by its Docker service name, never localhost.
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
