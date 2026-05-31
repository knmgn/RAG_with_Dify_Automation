#!/usr/bin/env bash
# End-to-end webhook tests for the §4-7 fully-local Docker setup.
#
# Usage:
#   1. Set N8N_WEBHOOK_TOKEN to the X-Auth-Token value you registered
#      in the n8n Header Auth credential:
#        export N8N_WEBHOOK_TOKEN="<your token here>"
#   2. Set INTENT_DISPATCHER_PATH to your Workflow 1 webhook UUID:
#        export INTENT_DISPATCHER_PATH="<uuid>"
#      (Default fallback below is the demo path; replace with yours.)
#   3. Run:
#        ./test_webhook.sh
#
# The script runs four sanity checks in order. Each one is independent;
# failures in earlier tests do not block later ones (we want to see all
# results to localize problems).

set -u

N8N_HOST="${N8N_HOST:-localhost}"
N8N_PORT="${N8N_PORT:-5678}"
N8N_WEBHOOK_TOKEN="${N8N_WEBHOOK_TOKEN:-CHANGEME_PUT_YOUR_TOKEN_HERE}"
INTENT_DISPATCHER_PATH="${INTENT_DISPATCHER_PATH:-8ee2e0e7-1aa3-4c37-9444-47c34dd9d509}"
FILE_SERVER_PATH="${FILE_SERVER_PATH:-files/expense-v3}"

BASE_URL="http://${N8N_HOST}:${N8N_PORT}"
DIFY_API_CONTAINER="${DIFY_API_CONTAINER:-docker-api-1}"

PASS="\033[0;32m[PASS]\033[0m"
FAIL="\033[0;31m[FAIL]\033[0m"
INFO="\033[0;36m[INFO]\033[0m"

echo "============================================================"
echo "  Demo-Logi RAG  ─  Webhook end-to-end test suite"
echo "============================================================"
echo "  Base URL              : ${BASE_URL}"
echo "  Intent Dispatcher path: /webhook/${INTENT_DISPATCHER_PATH}"
echo "  File Server path      : /webhook/${FILE_SERVER_PATH}"
echo "  Dify API container    : ${DIFY_API_CONTAINER}"
echo "============================================================"
echo

# ────────────────────────────────────────────────────────────────
# Test 1: n8n health from the host (basic connectivity)
# ────────────────────────────────────────────────────────────────
echo -e "${INFO} Test 1/4: n8n /healthz from host"
TEST1=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/healthz" || echo "ERR")
if [[ "${TEST1}" == "200" ]]; then
  echo -e "${PASS} n8n is reachable on host port ${N8N_PORT}"
else
  echo -e "${FAIL} n8n /healthz returned: ${TEST1}"
  echo "         Hint: Is the n8n container running? docker compose ps"
fi
echo

# ────────────────────────────────────────────────────────────────
# Test 2: n8n health from inside the Dify api container
# (Verifies that the demo-rag-net network is wired up correctly)
# ────────────────────────────────────────────────────────────────
echo -e "${INFO} Test 2/4: n8n /healthz from inside Dify api container"
TEST2=$(docker exec "${DIFY_API_CONTAINER}" \
  curl -s -o /dev/null -w "%{http_code}" "http://n8n_local:5678/healthz" 2>/dev/null \
  || echo "ERR")
if [[ "${TEST2}" == "200" ]]; then
  echo -e "${PASS} Dify api can reach n8n via internal Docker DNS (n8n_local)"
else
  echo -e "${FAIL} curl from Dify api returned: ${TEST2}"
  echo "         Hint: docker network inspect demo-rag-net"
  echo "               Verify both n8n_local and ${DIFY_API_CONTAINER} are listed."
fi
echo

# ────────────────────────────────────────────────────────────────
# Test 3: Intent Dispatcher (Workflow 1) end-to-end
# ────────────────────────────────────────────────────────────────
echo -e "${INFO} Test 3/4: Workflow 1 (Intent Dispatcher) returns success JSON"
PAYLOAD='{
  "intent": "request_expense_template",
  "user_id": "test_user_001",
  "user_query": "経費精算のフォーマットちょうだい",
  "metadata": { "template_key": "expense_template_v3" }
}'
RESP=$(curl -s -X POST "${BASE_URL}/webhook/${INTENT_DISPATCHER_PATH}" \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: ${N8N_WEBHOOK_TOKEN}" \
  -d "${PAYLOAD}")
if echo "${RESP}" | grep -q '"status":"success"'; then
  echo -e "${PASS} Workflow 1 returned success JSON"
  echo "         Body excerpt: $(echo "${RESP}" | head -c 120)..."
else
  echo -e "${FAIL} Workflow 1 did not return success JSON"
  echo "         Response: ${RESP}"
  echo "         Hint: Check that Workflow 1 is Active and the X-Auth-Token matches."
fi
echo

# ────────────────────────────────────────────────────────────────
# Test 4: File Server (Workflow 2) returns the xlsx binary
# ────────────────────────────────────────────────────────────────
echo -e "${INFO} Test 4/4: Workflow 2 (File Server) returns xlsx binary"
TMPDIR=$(mktemp -d)
TEST4_HTTP=$(curl -s -o "${TMPDIR}/got.xlsx" \
  -w "%{http_code} %{size_download}" \
  "${BASE_URL}/webhook/${FILE_SERVER_PATH}")
HTTP_STATUS=$(echo "${TEST4_HTTP}" | awk '{print $1}')
DOWNLOAD_SIZE=$(echo "${TEST4_HTTP}" | awk '{print $2}')
if [[ "${HTTP_STATUS}" == "200" && "${DOWNLOAD_SIZE}" -gt 1000 ]]; then
  echo -e "${PASS} Workflow 2 returned ${DOWNLOAD_SIZE} bytes (HTTP ${HTTP_STATUS})"
  echo "         File saved to: ${TMPDIR}/got.xlsx"
  echo "         File type: $(file -b "${TMPDIR}/got.xlsx" 2>/dev/null || echo 'unknown')"
else
  echo -e "${FAIL} Workflow 2 returned HTTP ${HTTP_STATUS}, ${DOWNLOAD_SIZE} bytes"
  echo "         Hint: Is Workflow 2 Active? Is templates/expense_template_v3.xlsx in place?"
  echo "               On macOS, did you run: xattr -c templates/expense_template_v3.xlsx"
fi
echo

echo "============================================================"
echo "  Test suite complete."
echo "============================================================"
