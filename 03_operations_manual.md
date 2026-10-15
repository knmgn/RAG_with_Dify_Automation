# Operations Manual — Demo-Logi-Bot (§4-7 fully local setup)

> Audience: the people who **operate** the deployed environment (internal IT, General Affairs administrators)
> Prerequisite: the environment is running, set up as described in `docker/README.md`
> Related: the reasoning behind each design value is in [`02_dify_chatflow_design.md`](./02_dify_chatflow_design.md)

This manual covers only what happens *after* the build: daily start and stop, swapping in a
revised policy, replacing the Excel template, backups, and first-line triage when something
goes wrong.

---

## 0. How this environment fits together (one-minute overview)

```
Browser ──80──→ [Dify]  ──internal network──→ [n8n] ──→ templates/*.xlsx
                   │                             ↑
                   └── OpenAI API (only egress)  └── browser downloads directly on 5678
```

| Container | Role | What breaks when it stops |
|---|---|---|
| `docker-nginx-1` | Dify front door (port 80) | The UI does not load |
| `docker-api-1` / `docker-worker-1` | Dify core | The bot does not respond |
| `docker-db_postgres-1` | Conversation logs, app settings | The bot does not respond |
| `docker-weaviate-1` | Vector store (search index of the policy) | Search returns zero hits and every question is refused |
| `docker-ssrf_proxy-1` | Relay for Dify's outbound traffic | Only file requests fail |
| `n8n_local` | File delivery | Only file requests fail |

**Data that leaves the host:** the user's question and the excerpts of policy text that
retrieval returned are sent to OpenAI. Everything else (the files themselves, conversation
logs, routing logic) stays on the company's server.

---

## 1. Daily operation

### Start and stop

```bash
# Start (Dify, then n8n. Either order works, but this one is safest)
cd ~/dify-local/docker && docker compose up -d
cd <this-repo>/docker/n8n && docker compose up -d

# Stop (data is kept)
cd ~/dify-local/docker && docker compose down
cd <this-repo>/docker/n8n && docker compose down
```

> ⚠️ **Do not use** `docker compose down -v`. `-v` deletes the volumes, and with them the
> conversation logs and the knowledge base.

> ⚠️ Always operate Dify **from the same directory**. See §4-8 ⑫ for why.
> To check where it is currently running from:
> ```bash
> docker inspect docker-api-1 --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
> ```

### Health check

```bash
# State of every container
docker ps --format 'table {{.Names}}\t{{.Status}}'

# End-to-end health check (3 tests, about 1 minute)
python3 scripts/test_e2e.py
```

If `test_e2e.py` reports 3/3 PASS, retrieval, the LLM, the n8n integration and file delivery
are all working. **Running this first thing in the morning is enough as the day's health check.**

### Logs

```bash
docker compose logs -f api          # Dify (run in ~/dify-local/docker)
docker logs -f n8n_local            # n8n
```

n8n's execution history is easier to read in the UI (<http://localhost:5678> → Executions).

---

## 2. When the policy is revised (re-embedding)

Use this when the policy moves to revision 4, a clause is added, and so on. **It takes about
5 minutes**, of which embedding takes 1–2.

### Procedure

```bash
# 1. Update the policy text
#    Edit 01_dummy_manual_demo_logistics.md
#    (always keep headings in the form ### 第N条（...）; see below)

# 2. Rebuild the knowledge base
python3 scripts/provision_knowledge.py --recreate

# 3. Measure retrieval quality
python3 scripts/measure_recall.py --threshold 0.3

# 4. Point the Chatflow at the new knowledge base
python3 scripts/provision_chatflow.py --recreate

# 5. Verify end to end
python3 scripts/test_e2e.py
```

### Why the Chatflow has to be rebuilt too

`--recreate` deletes and rebuilds the knowledge base, so **the dataset_id changes**.
The Chatflow's Knowledge Retrieval node stores the dataset_id directly, so without a rebuild it
keeps pointing at the old, deleted knowledge base. Skip step 4 and the bot refuses every
question.

### Rules for editing the policy

| Rule | Why |
|---|---|
| Keep clause headings in the form `### 第N条（...）` (Article N) | Chunks are split on these headings (§3-3 ①) |
| Keep each clause within 1,400 characters | Longer clauses get cut mid-way and retrieval quality drops |
| Keep the contact e-mail address in the text | The refusal message cites it |

If a clause exceeds 1,400 characters, raise `PARENT_MAX_CHARS` in
`scripts/provision_knowledge.py`. To check clause lengths:

```bash
python3 -c "
import re
text = open('01_dummy_manual_demo_logistics.md', encoding='utf-8').read()
for part in re.split(r'(?m)^(?=### )', text):
    if part.strip():
        print(len(part), part.splitlines()[0][:40])
" | sort -rn | head -5
```

### What to confirm after every revision

`measure_recall.py` must stay at **Recall@4 >= 90%**.
If it falls below that, update `TEST_QUERIES` in `scripts/measure_recall.py` to match the new
clauses and measure again. The test queries themselves may be out of date.

---

## 3. Replacing the expense template (xlsx)

### Procedure

```bash
# 1. Update the template (when regenerating it from the script)
pip install openpyxl
python3 scripts/build_expense_template.py

# 2. Replace the file n8n serves
cp 経費精算テンプレート_v3.xlsx docker/n8n/templates/expense_template_v3.xlsx

# 3. macOS only: strip extended attributes (important)
xattr -c docker/n8n/templates/expense_template_v3.xlsx

# 4. Verify delivery
curl -s -o /tmp/dl.xlsx -w "%{http_code} %{size_download}\n" \
  http://localhost:5678/webhook/files/expense-v3
file /tmp/dl.xlsx    # → Microsoft Excel 2007+
```

**No container restart is needed.** `docker/n8n/templates/` is a bind mount, so replacing the
file on the host takes effect immediately.

### Changing the file name

A new file name has to be changed in three places. **Miss one and delivery breaks.**

1. The actual file name in `docker/n8n/templates/`
2. The File Selector of the `Read/Write Files from Disk` node in n8n Workflow 2
   (`/home/node/.n8n-files/<new name>`)
3. The `Content-Disposition` header of `Respond to Webhook` in n8n Workflow 2
   (RFC 5987 form for Japanese names; see §4-8 ④ for how to generate it)

Afterwards, run `python3 scripts/export_n8n_workflows.py` to update the JSON in the repository.

> ⚠️ The file must live under `/home/node/.n8n-files`. This is n8n's allowlist restriction (§4-8 ①).

---

## 4. Changing what the bot says

| What to change | Where to edit |
|---|---|
| Answer tone, format, refusal message | `SYSTEM_PROMPT` in `scripts/provision_chatflow.py` |
| How questions are routed | `CLASSIFIER_INSTRUCTION` in the same file |
| The reply to a file request | `FILE_ANSWER_TEMPLATE` in the same file |
| The LLM used | `LLM_MODEL` in the same file |
| Number of results and threshold | `TOP_K` / `SCORE_THRESHOLD` in `scripts/provision_knowledge.py` |

After editing:

```bash
python3 scripts/provision_chatflow.py --recreate
python3 scripts/test_e2e.py
```

> 💡 You can also edit directly in the Dify admin UI, but those changes are not recorded in the
> scripts and are lost the next time `--recreate` runs. The recommended practice is to
> **experiment in the UI, then copy the final version into the script**. You can pull out what
> you built in the UI via "App → top-right menu → Export DSL".

---

## 5. Backup and restore

### What to back up

| Target | Location | Contents |
|---|---|---|
| Dify PostgreSQL | `<Dify dir>/docker/volumes/db/data` | App settings, conversation logs, knowledge metadata |
| Dify Weaviate | `<Dify dir>/docker/volumes/weaviate` | Vector index |
| Dify storage | `<Dify dir>/docker/volumes/app/storage` | Uploaded source files |
| n8n | Docker volume `n8n-local_n8n_data` | Workflows, credentials |
| Template | `docker/n8n/templates/` | The xlsx being served |

The Dify side uses bind mounts, so **copying the directory is all it takes**.

### Procedure (cold backup recommended)

```bash
DIFY_DIR=~/dify-local/docker
STAMP=$(date +%Y%m%d)

# 1. Stop (to guarantee consistency)
cd $DIFY_DIR && docker compose down
cd <this-repo>/docker/n8n && docker compose down

# 2. Copy Dify's data
tar czf ~/backup_dify_$STAMP.tar.gz -C $DIFY_DIR volumes

# 3. Copy the n8n volume
docker run --rm -v n8n-local_n8n_data:/data -v ~:/backup alpine \
  tar czf /backup/backup_n8n_$STAMP.tar.gz -C /data .

# 4. Restart
cd $DIFY_DIR && docker compose up -d
cd <this-repo>/docker/n8n && docker compose up -d
```

### Restore

Extract in the reverse order, then run `docker compose up -d`.
After a restore, always confirm health with `python3 scripts/test_e2e.py`.

> 💡 **The knowledge base and Chatflow can be rebuilt without a backup**
> (`provision_knowledge.py` → `provision_chatflow.py`).
> What you really cannot afford to lose is the **conversation logs** and the **n8n credentials**.
> If those two are safe, you can recover.

---

## 6. First-line triage

Start by running `python3 scripts/test_e2e.py`. Which test fails narrows down the cause.

| Failing test | Where to look |
|---|---|
| Only Test 1 (policy Q&A) | Knowledge retrieval, or the OpenAI API |
| Only Test 2 (guardrail) | The system prompt (has it been changed unintentionally?) |
| Only Test 3 (file request) | n8n, networking, or where the xlsx is placed |
| All of them | Dify core (api / postgres) is down |

### By symptom

| Symptom | What to check |
|---|---|
| **Every question gets "no provision found in the policy"** | ① Is the knowledge base empty? (`measure_recall.py`) ② Is the Chatflow pointing at an old dataset_id? (run step 4 of §2) ③ Are OpenAI embeddings failing? |
| **Only file requests fail** | ① Is `n8n_local` running in `docker ps`? ② Are the workflows Active? ③ Is `ssrf_proxy` on `demo-rag-net`? (§4-8 ⑩) |
| **The reply to a file request is empty** | Has the Chatflow's Code node (`parse_response`) gone missing? (§4-8 ⑨) |
| **The UI does not load** | Are `docker-nginx-1` and `docker-api-1` healthy in `docker ps`? |
| **Responses are unusually slow** | Latency on the OpenAI side. Check request times with `docker compose logs -f api` |
| **The download URL fails with `ERR_NAME_NOT_RESOLVED`** | Does the `download_url` returned by n8n use `localhost:5678`? (`n8n_local:5678` does not work; §4-7) |

### Last resort

Even if containers break, the data survives in the bind mounts / volumes.

```bash
cd ~/dify-local/docker && docker compose down && docker compose up -d
```

If that does not fix it, rebuild the knowledge base and Chatflow (no data loss, about 5 minutes):

```bash
python3 scripts/provision_knowledge.py --recreate
python3 scripts/provision_chatflow.py --recreate
python3 scripts/test_e2e.py
```

---

## 7. Routine maintenance (recommended frequency)

| Frequency | Task |
|---|---|
| Every business day | `python3 scripts/test_e2e.py` (confirm 3/3 PASS) |
| Monthly | Take a backup. Check Recall@4 with `measure_recall.py` |
| On policy revision | The re-embedding procedure in §2 |
| Quarterly | Consider upgrading Dify / n8n (always back up first) |
| As needed | Check OpenAI API spend |

### Cost estimate

OpenAI is the only external charge.

- **Embeddings:** rebuilding for one policy (about 6,400 characters) costs a few yen (well under
  USD 0.10) per run, and only on revision
- **LLM (gpt-4o-mini):** each question sends roughly 2,000–4,000 input tokens (system prompt plus
  four retrieved chunks). Cost scales with the number of questions

Check OpenAI's pricing page for current rates.
