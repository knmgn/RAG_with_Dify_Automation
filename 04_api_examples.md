# API Examples (curl / Postman)

> Audience: developers integrating this bot into existing internal systems (portals, Slack, business apps)
> Prerequisite: the environment is running, set up as described in `docker/README.md`
> Related: [`02_dify_chatflow_design.md`](./02_dify_chatflow_design.md) / [`03_operations_manual.md`](./03_operations_manual.md)

**Every command in this document was run against the live environment and its response checked.**
Use it as a reference when you want to **call the bot through the API from your own UI** rather
than embed it in an internal portal with an iframe.

> The queries and answers are in Japanese because the demo knowledge base is Japanese.
> English glosses are given in comments.

---

## 0. Setup: issue an API key

Calling Dify's Service API requires a per-app API key.

**From the UI:** open the app → left menu "API Access" → top-right "API Key" → "Create new secret key"

**From a script:**

```bash
python3 -c "
import json
from dify_console import connect, load_env
from test_e2e import get_api_key
c = connect(load_env())
app_id = json.load(open('scripts/.provision_state.json'))['app_id']
print(get_api_key(c, app_id))
"
```

The examples below read the key from an environment variable. Keys start with `app-` and are 28 characters long.

```bash
export DIFY_API_KEY="app-xxxxxxxxxxxxxxxxxxxxxxxx"
export DIFY_BASE="http://localhost"
```

> ⚠️ This key has **full access to the app**. Never embed it in front-end JavaScript.
> Always call the API from the server side.

---

## 1. Policy Q&A (synchronous, blocking)

The most basic call. The full answer comes back in one response once it is complete.

```bash
# "How much is a late-night taxi home?"
curl -s -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "深夜帰りのタクシー代いくら？",
    "response_mode": "blocking",
    "user": "employee-0042"
  }'
```

**Response (excerpt)**

```json
{
  "event": "message",
  "message_id": "…",
  "conversation_id": "…",
  "mode": "advanced-chat",
  "answer": "【結論】\n深夜帰宅時のタクシー代は、1回あたり15,000円（消費税込）が上限です。\n…",
  "metadata": {
    "usage": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_price": "…",
      "currency": "USD",
      "latency": 0.0
    },
    "retriever_resources": [
      {
        "position": 1,
        "dataset_name": "社内規程ナレッジ",
        "document_name": "DL-HR-RG-2024-007_旅費交通費・経費精算および労務手続き規定.txt",
        "score": 0.6438,
        "content": "第5条（タクシー代の支給要件）…",
        "doc_metadata": { "doc_id": "DL-HR-RG-2024-007", "doc_version": "v3", "…": "…" }
      }
    ]
  },
  "created_at": 1785965600
}
```

The `answer` reads: "[Conclusion] A late-night taxi home is capped at JPY 15,000 per ride (tax included). …"

| Field | Use |
|---|---|
| `answer` | The answer text shown to the user |
| `conversation_id` | Used to continue the conversation (§3) |
| `metadata.retriever_resources` | **Use for citation display and audit logs.** It carries `score` and `doc_metadata`, so you can record *which policy, at which revision*, the answer was based on |
| `metadata.usage` | Token counts and cost. Useful for cost allocation |

Put your own employee ID in `user`. Dify separates conversation logs by this value.

---

## 2. Policy Q&A (streaming)

Use this when building a chat UI. Responses arrive as SSE (Server-Sent Events).

```bash
# "How much is the night-shift allowance?"
curl -s -N -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "夜勤手当いくら？",
    "response_mode": "streaming",
    "user": "employee-0042"
  }'
```

**Event sequence**

```
event: ping

data: {"event":"workflow_started","conversation_id":"…","message_id":"…"}

data: {"event":"node_started","data":{"title":"インテント分類",…}}

data: {"event":"node_finished","data":{"title":"ナレッジ検索",…}}

data: {"event":"message","answer":"【結","…"}
data: {"event":"message","answer":"論】","…"}
      …

data: {"event":"message_end","metadata":{"usage":{…},"retriever_resources":[…]}}
```

(`インテント分類` = intent classifier node, `ナレッジ検索` = knowledge retrieval node.)

| Event | How to handle it |
|---|---|
| `message` | Concatenate `answer` and stream it to the screen |
| `node_started` / `node_finished` | Can drive a progress indicator ("Searching the policy…"). Safe to ignore |
| `message_end` | `retriever_resources` arrives here. Render citations at this point |
| `error` | Contains the error details |

> 💡 When recording the demo video shot where "n8n Executions update in real time",
> keeping Dify in streaming mode too makes the processing visibly progress.

---

## 3. Continuing a conversation

Pass the `conversation_id` from the previous response to carry the context forward.

```bash
# "Do I need a receipt for that?"
curl -s -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "それって領収書いる？",
    "conversation_id": "<conversation_id from the previous response>",
    "response_mode": "blocking",
    "user": "employee-0042"
  }'
```

> ⚠️ Manage `conversation_id` together with `user`. Passing a `conversation_id` that
> belongs to a different `user` returns 404.

### Fetching conversation history

```bash
# List conversations
curl -s -G "$DIFY_BASE/v1/conversations" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  --data-urlencode "user=employee-0042" \
  --data-urlencode "limit=20"

# Messages in one conversation
curl -s -G "$DIFY_BASE/v1/messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  --data-urlencode "user=employee-0042" \
  --data-urlencode "conversation_id=<conversation_id>"
```

---

## 4. File request (Dify → n8n → download)

Ask the bot for "the format" and a download URL comes back through n8n.
**The call is exactly the same as in §1.** The Chatflow routes it internally.

```bash
# "Send me the expense report format."
curl -s -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "経費精算のフォーマットちょうだい",
    "response_mode": "blocking",
    "user": "employee-0042"
  }' | python3 -c "import json,sys; print(json.load(sys.stdin)['answer'])"
```

**Output**

```
経費精算テンプレートをご用意しました。下記URLからダウンロードしてください。

📎 **経費精算テンプレート_v3.xlsx**
http://localhost:5678/webhook/files/expense-v3

【ご注意】
- 提出期限：毎月25日17:00必着
- マクロを必ず有効化してください（規程第9条第4項）

【引用元】
規程：DL-HR-RG-2024-007 第8条・第9条
窓口：総務部 佐藤（内線1234）／ 経理部 鈴木（内線1456）
```

In English: "Here is the expense template; download it from the URL below. [Note] Deadline:
must arrive by 17:00 on the 25th of each month. Always enable macros (Art. 9 §4).
[Source] DL-HR-RG-2024-007 Arts. 8 and 9. Contact: Sato, General Affairs (ext. 1234) /
Suzuki, Accounting (ext. 1456)."

---

## 5. Calling n8n directly

For testing n8n alone, without Dify. Useful for isolating faults.

### Workflow 1: Intent Dispatcher (authenticated)

```bash
export N8N_WEBHOOK_TOKEN="<the value set in the Header Auth credential>"
export DISPATCHER_PATH="8ee2e0e7-1aa3-4c37-9444-47c34dd9d509"

curl -s -X POST "http://localhost:5678/webhook/$DISPATCHER_PATH" \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: $N8N_WEBHOOK_TOKEN" \
  -d '{
    "intent": "request_expense_template",
    "user_id": "employee-0042",
    "user_query": "経費精算のフォーマットちょうだい",
    "metadata": { "template_key": "expense_template_v3" }
  }'
```

**Response**

```json
{
  "status": "success",
  "intent": "request_expense_template",
  "filename": "経費精算テンプレート_v3.xlsx",
  "download_url": "http://localhost:5678/webhook/files/expense-v3",
  "message": "経費精算テンプレートをご用意しました。下記URLからダウンロードしてください。",
  "regulation_ref": "DL-HR-RG-2024-007 第8条・第9条",
  "deadline": "毎月25日17:00必着",
  "macro_warning": "マクロを必ず有効化してください（規程第9条第4項）"
}
```

| Response | Meaning |
|---|---|
| 200 + `"status":"success"` | OK |
| 401 / `Authorization data is wrong!` | `X-Auth-Token` mismatch. Check that the credential's `Name` field holds the header name (§4-8 ①) |
| 400 + `Unknown intent` | Unsupported `intent` value; the request fell through to the Fallback output |
| 404 | The workflow is not Active |

Checking an unsupported intent:

```bash
curl -s -X POST "http://localhost:5678/webhook/$DISPATCHER_PATH" \
  -H "Content-Type: application/json" -H "X-Auth-Token: $N8N_WEBHOOK_TOKEN" \
  -d '{"intent":"request_unknown_thing","user_id":"t"}'
```

### Workflow 2: File Server (no authentication)

The path itself is a hard-to-guess string that stands in for a token.

```bash
curl -s -o /tmp/template.xlsx -w "HTTP %{http_code} / %{size_download} bytes / %{content_type}\n" \
  http://localhost:5678/webhook/files/expense-v3

file /tmp/template.xlsx    # → Microsoft Excel 2007+
```

Saving with the Japanese file name (browsers use the Japanese name automatically):

```bash
curl -OJ http://localhost:5678/webhook/files/expense-v3
# curl saves it under the ASCII fallback name expense_template_v3.xlsx (§4-8 ④)
```

---

## 6. Health checks

For registering with a monitoring tool (Uptime Kuma, etc.).

```bash
# n8n
curl -s -o /dev/null -w "n8n: %{http_code}\n" http://localhost:5678/healthz

# Dify (web app entry point)
curl -s -o /dev/null -w "dify: %{http_code}\n" http://localhost/

# Dify → n8n internal connectivity (across the Docker network)
docker exec docker-api-1 curl -s -o /dev/null -w "internal: %{http_code}\n" \
  http://n8n_local:5678/healthz
```

> ⚠️ A 200 on the third check does not guarantee the Chatflow can reach n8n,
> because real requests go through squid (`ssrf_proxy`). **The real connectivity check is
> `python3 scripts/test_e2e.py`** (§4-8 ⑩).

---

## 7. Testing retrieval only (for tuning)

Shows search results and scores without generating an answer. Use it to tune the threshold and chunk settings.

```bash
# "I went over the taxi cap"
python3 -c "
import json
from dify_console import connect, load_env
c = connect(load_env())
ds = json.load(open('scripts/.provision_state.json'))['dataset_id']
r = c.post(f'/datasets/{ds}/hit-testing', {'query': 'タクシー上限超えた'})
for rec in r.get('records', []):
    print(round(rec['score'], 4), '|', rec['segment']['content'][:60].replace(chr(10), ' '))
"
```

To evaluate all ten queries at once, use `python3 scripts/measure_recall.py --threshold 0.3`.

---

## 8. Importing into Postman

The curl commands above import into Postman as-is.

1. Postman → top-left "Import" → "Raw text"
2. Paste the curl command → "Continue" → "Import"

Defining `DIFY_BASE` / `DIFY_API_KEY` / `N8N_WEBHOOK_TOKEN` as collection variables makes
switching between environments (development / production) easy.

> ⚠️ **Never share or export a collection that contains API keys or tokens.**
> Keep them in a Postman "Environment" and leave only variable references in the collection.

---

## 9. Production integration notes

| Item | PoC (this setup) | Production |
|---|---|---|
| Protocol | HTTP | HTTPS required (otherwise API keys travel in plain text) |
| API key storage | Environment variables | Secret manager |
| Caller | Local | Server side only. Never call directly from the browser |
| `user` field | Any string | Fix it to the employee ID so conversation logs line up |
| Download URL | `localhost:5678` | Internal DNS name (e.g. `n8n.example.co.jp`). Change via the `WEBHOOK_URL` environment variable |
| Rate limiting | None | Implement at the reverse proxy |
| Audit logs | Dify conversation logs | Record `doc_id` / `doc_version` from `retriever_resources` in your own logs (§3-3 ⑥) |
