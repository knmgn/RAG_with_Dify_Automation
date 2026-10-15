# API Examples (curl / Postman)

> Audience: developers integrating this bot into existing internal systems (portals, Slack, business apps)
> Prerequisite: the environment is running, set up as described in `docker/README.md`
> Related: [`02_dify_chatflow_design.md`](./02_dify_chatflow_design.md) / [`03_operations_manual.md`](./03_operations_manual.md)

Use this as a reference when you want to **call the bot through the API from your own UI** rather
than embed it in an internal portal with an iframe.

> Every request in this document was run against the live environment on the Japanese edition
> (tag `v1-ja`). The request shapes are unchanged in the English edition. The response bodies below
> show the English edition's content and are abbreviated with `…`.

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
    "query": "How much can I claim for a late-night ride home?",
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
  "answer": "**Answer**\nA ride home after work ends past 11:00 PM is reimbursed up to USD 100 per ride (tax and tip included).\n…",
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
        "dataset_name": "Internal Policy Knowledge",
        "document_name": "DL-HR-RG-2024-007_Travel_Expense_and_HR_Procedures_Policy.txt",
        "score": 0.6438,
        "content": "Article 5 (Late-Night Rideshare and Taxi)…",
        "doc_metadata": { "doc_id": "DL-HR-RG-2024-007", "doc_version": "v3", "…": "…" }
      }
    ]
  },
  "created_at": 1785965600
}
```

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
curl -s -N -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "How much is the night shift differential?",
    "response_mode": "streaming",
    "user": "employee-0042"
  }'
```

**Event sequence**

```
event: ping

data: {"event":"workflow_started","conversation_id":"…","message_id":"…"}

data: {"event":"node_started","data":{"title":"Intent classifier",…}}

data: {"event":"node_finished","data":{"title":"Knowledge retrieval",…}}

data: {"event":"message","answer":"**Ans","…"}
data: {"event":"message","answer":"wer**","…"}
      …

data: {"event":"message_end","metadata":{"usage":{…},"retriever_resources":[…]}}
```

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
curl -s -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "Do I need a receipt for that?",
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
curl -s -X POST "$DIFY_BASE/v1/chat-messages" \
  -H "Authorization: Bearer $DIFY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "Send me the expense report template.",
    "response_mode": "blocking",
    "user": "employee-0042"
  }' | python3 -c "import json,sys; print(json.load(sys.stdin)['answer'])"
```

**Output**

```
Here is the expense report template. Download it from the link below.

📎 **expense_template_v3.xlsx**
http://localhost:5678/webhook/files/expense-v3

**Please note**
- Deadline: Must be received by 5:00 PM on the 25th of each month
- Macros must be enabled (Article 9, Paragraph 4)

**Source**
Policy: DL-HR-RG-2024-007 Articles 8 and 9
Contacts: People Operations (ext. 1234) / Accounts Payable (ext. 1456)
```

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
    "user_query": "Send me the expense report template.",
    "metadata": { "template_key": "expense_template_v3" }
  }'
```

**Response**

```json
{
  "status": "success",
  "intent": "request_expense_template",
  "filename": "expense_template_v3.xlsx",
  "download_url": "http://localhost:5678/webhook/files/expense-v3",
  "message": "Here is the expense report template. Download it from the link below.",
  "regulation_ref": "DL-HR-RG-2024-007 Articles 8 and 9",
  "deadline": "Must be received by 5:00 PM on the 25th of each month",
  "macro_warning": "Macros must be enabled (Article 9, Paragraph 4)"
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

Saving under the server-provided file name:

```bash
curl -OJ http://localhost:5678/webhook/files/expense-v3
# saved as expense_template_v3.xlsx (from the Content-Disposition header)
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
python3 -c "
import json
from dify_console import connect, load_env
c = connect(load_env())
ds = json.load(open('scripts/.provision_state.json'))['dataset_id']
r = c.post(f'/datasets/{ds}/hit-testing', {'query': 'My rideshare went over the cap'})
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
| Download URL | `localhost:5678` | Internal DNS name (e.g. `n8n.example.com`). Change via the `WEBHOOK_URL` environment variable |
| Rate limiting | None | Implement at the reverse proxy |
| Audit logs | Dify conversation logs | Record `doc_id` / `doc_version` from `retriever_resources` in your own logs (§3-3 ⑥) |
