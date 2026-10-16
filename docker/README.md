# Local Docker Stack — Dify Self-Hosted × n8n × Local File Delivery

> **Fully on-premises setup:** a PoC environment for small and mid-sized companies that combines Dify high-precision RAG with n8n business automation without sending any company data to an external cloud. This is the reference implementation of §4-7 / §4-8 of the design doc `02_dify_chatflow_design.md`.

## Why this setup?

What business owners at small and mid-sized companies worry about most is **"Will our data get sucked into someone's cloud?"** In this setup:

- **Policy documents, expense templates and conversation logs** are all stored in Docker volumes on the company's own server
- **Calls from Dify to n8n** travel over the internal Docker network (`demo-rag-net`) and never leave the host
- **File download URLs** are `http://localhost:5678/...` (internal)
- **The only external traffic** is the LLM API call (OpenAI / Anthropic). Even that can be replaced with a local LLM such as Ollama (extension roadmap, Phase 5)

→ You can say "your data never leaves the building" and mean it. That is often what wins the deal.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Docker host (on-prem server or development Mac)                 │
│                                                                  │
│  ┌─────────── demo-rag-net (external bridge) ──────────────┐    │
│  │                                                           │    │
│  │  [Dify Self-Hosted]            [n8n Self-Hosted]          │    │
│  │  - api / worker / web          - Workflow 1: Dispatcher   │    │
│  │  - postgres / redis            - Workflow 2: File Server  │    │
│  │  - weaviate / sandbox          - port 5678                │    │
│  │  - nginx (port 80)             - templates/ (bind mount)  │    │
│  │                                                           │    │
│  └───────────────────────────────────────────────────────────┘    │
│        ↑ Browser:80                  ↑ Browser:5678              │
└────────┼──────────────────────────────┼──────────────────────────┘
         │                              │
  [Employee's browser]          [Employee's browser]
                                (clicks the link to download)
```

## Directory layout

```
docker/
├── README.md                       ← this file
├── n8n/
│   ├── docker-compose.yml          ← n8n + templates volume + joins the shared network
│   ├── templates/
│   │   └── (place expense_template_v3.xlsx here)
│   └── workflows/                  ← exported n8n workflows (ready to import)
├── dify/
│   └── docker-compose.override.yaml ← overlay on the official Dify compose (network changes only)
└── test/
    └── test_webhook.sh             ← 4-stage connectivity test script
```

## Quick start (full setup)

### Prerequisites
- Docker Desktop installed (4 GB RAM minimum, 8 GB recommended)
- Tested on macOS and Linux (Windows not tested)
- Ports `80` and `5678` free on the host

### Step 1: Create the shared network (once)

```bash
docker network create demo-rag-net
```

### Step 2: Prepare Dify Self-Hosted

```bash
# Clone a Dify release (not main) into your home directory.
# The English edition was measured on 1.17.1.
git clone --branch 1.17.1 --depth 1 https://github.com/langgenius/dify.git ~/dify-local

# Copy this repository's override file into Dify's docker/ directory
cp docker/dify/docker-compose.override.yaml ~/dify-local/docker/

# Prepare Dify's environment file
cd ~/dify-local/docker
cp .env.example .env
```

> ⚠️ **Clone Dify in one place only.** The compose project name comes from the
> current directory name, and Dify is always operated from its `docker/` directory, so
> **the project name is `docker` wherever you clone it**.
> With two clones, `docker compose up -d` from either one controls the same set of
> containers, but the compose files, `.env` and templates are read from whichever
> directory you ran it in. A setting you fixed in one clone is reverted the moment
> someone runs `up -d` from the other (design doc §4-8 ⑫).
>
> To check where the stack is currently running from:
> ```bash
> docker inspect docker-api-1 \
>   --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
> ```
> PostgreSQL and Weaviate data live under that directory as bind mounts.

> ⚠️ Docker Compose automatically layers `docker-compose.override.yaml` on top of the main YAML (no manual merge needed).
>
> The override adds `demo-rag-net` to `api` and `worker` **and also to `ssrf_proxy`**,
> and sets `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS: n8n_local`.
> Dify sends HTTP Request node traffic through squid (`ssrf_proxy`), so without both
> changes the Chatflow cannot reach n8n.
> Miss this and you get "the connectivity tests pass, but the Chatflow alone fails" (design doc §4-8 ⑩).

### Step 3: Place the xlsx template

Copy `expense_template_v3.xlsx` (the expense template) from the repository root into `docker/n8n/templates/`:

```bash
# From the repository root
cp expense_template_v3.xlsx docker/n8n/templates/expense_template_v3.xlsx

# On macOS, strip extended attributes if the file came through a Google Drive sync folder (important)
xattr -c docker/n8n/templates/expense_template_v3.xlsx
```

> 💡 If you skip `xattr -c`, n8n on a Mac cannot read the file and fails with "Operation not permitted" (EPERM). See design doc §4-8 ③. This does not happen on Linux.

### Step 4: Start both stacks

```bash
# Start n8n
cd docker/n8n
docker compose up -d

# Start Dify (5-10 minutes on first start because of image pulls)
cd ~/dify-local/docker
docker compose up -d
```

### Step 5: Check status

```bash
# Confirm every container is healthy
cd ~/dify-local/docker && docker compose ps
cd <this-repo>/docker/n8n && docker compose ps
```

Every container should show `running` or `(healthy)`.

### Step 6: Open the UIs

| Service | URL | Purpose |
|---|---|---|
| Dify | <http://localhost/install> | Create the admin account on first visit |
| n8n | <http://localhost:5678> | Edit and monitor workflows |

### Step 7: Import the n8n workflows

The exported JSON files are included in `docker/n8n/workflows/`.

| File | What it does |
|---|---|
| `workflow_1_intent_dispatcher.json` | Receives POST → Switch → JSON response (returns `download_url`) |
| `workflow_2_file_server.json` | Receives GET → reads the file → binary response (xlsx) |

Import them from the n8n UI (<http://localhost:5678>) via the top-right menu → **Import from File**.
The CLI works too:

```bash
docker cp docker/n8n/workflows/workflow_1_intent_dispatcher.json n8n_local:/tmp/
docker exec n8n_local n8n import:workflow --input=/tmp/workflow_1_intent_dispatcher.json
```

After importing, two things remain:

1. **Create the Header Auth credential and re-link it**
   The JSON contains only a **reference** to the credential, not the token itself (as it should).
   Open the Webhook node in Workflow 1 and create the credential again.
   - Credential type: `Header Auth`
   - **Put the header name `X-Auth-Token` in the `Name` field.** It is not the credential's
     display name. Get this wrong and you see `Authorization data is wrong!`, a trap next to §4-8 ①.
   - Put the shared secret (any random string) in the `Value` field
   - Set the same value as the Dify environment variable `N8N_WEBHOOK_TOKEN`
     (the reliable way is to write it into `scripts/.dify_admin.env` and run `provision_chatflow.py`)

2. **Activate both workflows**

> 💡 To re-export from your own environment, use `python3 scripts/export_n8n_workflows.py`.
> The raw output of `n8n export:workflow` includes the **owner's e-mail address** in its
> `shared` block, so it cannot be committed as-is. The script strips it.

### Step 8: Connectivity test

Once the n8n workflows are active, run the bundled script for a 4-stage connectivity check:

```bash
# The value registered in the n8n Header Auth credential
export N8N_WEBHOOK_TOKEN="<your token>"
export INTENT_DISPATCHER_PATH="<workflow1 webhook UUID>"

# Run
./docker/test/test_webhook.sh
```

Expected output:

```
[INFO] Test 1/4: n8n /healthz from host
[PASS] n8n is reachable on host port 5678

[INFO] Test 2/4: n8n /healthz from inside Dify api container
[PASS] Dify api can reach n8n via internal Docker DNS (n8n_local)

[INFO] Test 3/4: Workflow 1 (Intent Dispatcher) returns success JSON
[PASS] Workflow 1 returned success JSON

[INFO] Test 4/4: Workflow 2 (File Server) returns xlsx binary
[PASS] Workflow 2 returned 15078 bytes (HTTP 200)
```

If all four pass, the full Dify → n8n chain is working.

## The "two URLs" design (key design decision)

| Path | URL used | Why |
|---|---|---|
| Dify → n8n (internal call) | `http://n8n_local:5678/webhook/<UUID>` | Service-name resolution inside the Docker network |
| Browser → file download | `http://localhost:5678/webhook/files/expense-v3` | The browser cannot see the Docker network, so it goes through the port published on the host |

The `download_url` field that n8n returns to Dify **must use the `localhost:5678` URL**. With `n8n_local:5678` the browser fails with `ERR_NAME_NOT_RESOLVED`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `cannot expose privileged port 80` (rootless Docker) | Publish nginx on an unprivileged loopback port: add `EXPOSE_NGINX_PORT=127.0.0.1:8080` and `EXPOSE_NGINX_SSL_PORT=127.0.0.1:8443` to Dify's `.env`, then set `DIFY_BASE_URL=http://localhost:8080` in `scripts/.dify_admin.env` |
| Running on a VPS | Docker-published ports bypass the host firewall. Keep every port on `127.0.0.1` (n8n and the plugin daemon already are, via this repo's compose files) and reach the UIs through an SSH tunnel: `ssh -L 8080:localhost:8080 -L 5678:localhost:5678 user@host` |
| Out-of-memory error on `docker compose up` | Docker Desktop → Settings → Resources → set Memory to 8 GB or more |
| Dify `/install` does not load | Check with `docker compose ps` that nginx and api are healthy |
| Connection refused in connectivity Test 2 | Check with `docker network inspect demo-rag-net` that both containers joined the network |
| **All connectivity tests pass, but the Chatflow alone fails with `Reached maximum retries for URL http://n8n_local:5678/...`** | **`ssrf_proxy` has not joined `demo-rag-net`.** Dify's HTTP Request goes out through squid, so squid, not api, does the name resolution. After applying the override, run `docker compose up -d ssrf_proxy` |
| **`Access to '...' was blocked by SSRF protection`** | squid's ACL rejects private destinations. Check that the override's `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS: n8n_local` took effect: `docker exec docker-ssrf_proxy-1 cat /etc/squid/dify_allow_private.conf` |
| **The bot always answers "no provision found in the policy"** | ① Knowledge retrieval returns zero hits (e.g. a rate-limited Rerank API) ② The LLM node's context variable is not `{{#context#}}`. Design doc §4-8 ⑦ ⑧ |
| **The answer to a file request comes back empty** | The HTTP Request node's `body` is a string, so `body.message` cannot be referenced. A Code node is needed to parse the JSON. Design doc §4-8 ⑨ |
| EPERM in n8n Read/Write Files | Strip the xlsx's extended attributes with `xattr -c` (macOS only) |
| "Allowed paths" error in n8n Read/Write Files | Check that the file is under `/home/node/.n8n-files` |
| `Unused Respond to Webhook node found` on the webhook | Set the Webhook node's Respond option to `Using 'Respond to Webhook' Node`, and put a Respond node on every Switch branch |

## Additional considerations for production

This PoC setup **assumes development and internal demos**. A production delivery needs these changes:

| Item | PoC | Production |
|---|---|---|
| Host | Mac / development machine | On-prem server or private VPS |
| Exposed ports | `localhost:80` `localhost:5678` | Reverse proxy + internal DNS (e.g. `https://dify.example.com/`) |
| TLS | None (HTTP) | Required, e.g. Let's Encrypt |
| n8n authentication | Header Auth + hard-to-guess path | + IP allowlist (internal network only) |
| Backups | Optional | Scheduled snapshots of postgres + n8n_data + the Weaviate vector store |
| Monitoring | `docker compose ps` | Prometheus + Grafana / Uptime Kuma |
| Log aggregation | `docker compose logs` | Loki / Datadog, etc. |

These are part of the delivery checklist in design doc §7.

## Related documents

- [`../02_dify_chatflow_design.md`](../02_dify_chatflow_design.md) — design doc (§4-7 and §4-8 are the source for this setup)
- [`../01_policy_nexus_logistics.md`](../01_policy_nexus_logistics.md) — the dummy policy text fed to the bot
- [`../scripts/build_expense_template.py`](../scripts/build_expense_template.py) — xlsx regeneration script

## License

Provided as dummy material. Not affiliated with any real company, person, address or phone number.
