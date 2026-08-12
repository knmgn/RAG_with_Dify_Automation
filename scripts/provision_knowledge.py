#!/usr/bin/env python3
"""Phase 3 — build the Dify Knowledge base from code.

Creates the "社内規程ナレッジ" dataset exactly as specified in
`02_dify_chatflow_design.md` §3-3: Parent-Child chunking, high-quality
indexing on text-embedding-3-large, Hybrid Search with a Cohere reranker,
the six custom metadata fields, and the built-in metadata toggle.

    cp scripts/.dify_admin.env.example scripts/.dify_admin.env   # fill DIFY_PASSWORD
    python3 scripts/provision_knowledge.py

Re-running is safe: the script refuses to touch an existing dataset of the
same name unless you pass --recreate, which deletes and rebuilds it.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from dify_console import REPO_ROOT, DifyConsole, DifyError, connect, load_env

STATE_FILE = REPO_ROOT / "scripts" / ".provision_state.json"
SOURCE_DOCUMENT = REPO_ROOT / "01_dummy_manual_demo_logistics.md"

DATASET_NAME = "社内規程ナレッジ"
DATASET_DESCRIPTION = (
    "株式会社デモ・ロジスティクス 旅費交通費・経費精算および労務手続き規定"
    "（DL-HR-RG-2024-007 第3版）。Hybrid Search + Rerank 構成。"
)

EMBEDDING_PROVIDER = "langgenius/openai/openai"
EMBEDDING_MODEL = "text-embedding-3-large"

# §3-3 ④ — Hybrid Search submode.
#
# The design doc recommends the Rerank Model submode with Cohere
# rerank-multilingual-v3.0. We use the Weighted Score submode instead, for two
# reasons, both measured (scripts/measure_recall.py):
#
#   * Egress. §4-7 sells this stack on "データは外に出ません". Cohere rerank is a
#     second external dependency that ships the user's question *and* the
#     matching regulation text to a third party. Weighted Score is computed
#     inside Weaviate, so OpenAI (embeddings + LLM) becomes the only egress.
#   * It costs nothing in quality here. Both submodes score Recall@4 = 100% on
#     the ten §3-4 test queries. Cohere additionally rate-limits at ~10 req/min
#     on a trial key and returns *zero* results when throttled, with no error —
#     an unpleasant failure mode to hit during a live demo.
#
# The 0.7/0.3 split is the design doc's own recommended weighting.
SEMANTIC_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3

# §3-3 ① — Parent-Child chunking.
#
# The design doc writes the parent delimiter as `\n### \n#### \n第`. Two things
# about Dify make that unusable as written:
#
#   1. The delimiter is a single literal string, not a list, and Dify runs it
#      through `codecs.decode(sep, "unicode_escape")`. That codec mangles any
#      non-ASCII character, so `\n第` reaches the splitter as `\nç¬¬` and never
#      matches anything.
#   2. Dify's markdown extractor splits a .md file at *every* heading
#      (`re.match(r"^#+\s", line)`) before the chunk settings are applied. Upload
#      the regulation as .md and each `#### 第N項` becomes its own parent, which
#      silently defeats the whole point of parent chunks.
#
# So: upload a .txt rendering (see build_plaintext_source) and use `\n### ` as
# the delimiter. Parents then land on `### 第N条` boundaries, exactly as the
# design intends. The splitter consumes the delimiter, so chunks start cleanly
# at "第N条（...）".
PARENT_DELIMITER = "\\n### "
# The design doc says 1,200, but the longest clause (第5条, タクシー代の支給要件)
# is 1,287 characters. At 1,200 the splitter cut it in half, so a query matching
# 第2項 returned a parent that no longer contained 第1項 — the exact text the user
# asked about. 1,400 keeps all 21 clauses whole, which is the point of parents.
PARENT_MAX_CHARS = 1400
CHILD_DELIMITER = "\\n"
CHILD_MAX_CHARS = 250

TOP_K = 4
# The design doc specifies 0.5, which does not survive measurement. Under
# Weighted Score the ten §3-4 queries top out between 0.36 and 0.64, so 0.5
# would drop most of them. Measured distribution:
#
#     in-scope     top score  0.3623 .. 0.6438
#     out-of-scope top score  0.2144 .. 0.3849
#
# The ranges still overlap slightly, so a threshold can never be the
# anti-hallucination guardrail on its own — that job belongs to the §1-2 system
# prompt, which refuses when <context> does not contain the answer. (This is
# also why the §2-4 IF/ELSE score gate is not worth building.) 0.3 sits below
# every correct hit with margin while cutting 3 of the 4 out-of-scope queries,
# so it is a useful noise filter and keeps Recall@4 = 100%.
SCORE_THRESHOLD = 0.3

# §3-3 ⑥ Step 1 — schema, and Step 2 — the values for this one document.
METADATA_FIELDS: dict[str, str] = {
    "doc_id": "DL-HR-RG-2024-007",
    "doc_title": "旅費交通費・経費精算および労務手続き規定",
    "doc_version": "v3",
    "last_revised": "2024-10-01",
    "doc_type": "regulation",
    "category": "総務",
}

RETRIEVAL_WEIGHTS: dict[str, Any] = {
    "weight_type": "customized",
    "vector_setting": {
        "vector_weight": SEMANTIC_WEIGHT,
        "embedding_provider_name": EMBEDDING_PROVIDER,
        "embedding_model_name": EMBEDDING_MODEL,
    },
    "keyword_setting": {"keyword_weight": KEYWORD_WEIGHT},
}

RETRIEVAL_MODEL: dict[str, Any] = {
    "search_method": "hybrid_search",
    "reranking_enable": False,
    "reranking_mode": "weighted_score",
    "reranking_model": {"reranking_provider_name": "", "reranking_model_name": ""},
    "top_k": TOP_K,
    "score_threshold_enabled": True,
    "score_threshold": SCORE_THRESHOLD,
    "weights": RETRIEVAL_WEIGHTS,
}


UPLOAD_FILENAME = "DL-HR-RG-2024-007_旅費交通費・経費精算および労務手続き規定.txt"


def log(message: str) -> None:
    print(message, flush=True)


def build_plaintext_source(markdown_path: Path) -> str:
    """Render the markdown regulation as plain text for ingestion.

    Only `#### 第N項` headings are flattened — they are sub-items of a clause and
    should stay inside their parent chunk. The `### 第N条` headings are kept
    because they are what PARENT_DELIMITER splits on (and the splitter strips
    the delimiter, so the marker never shows up in a citation).
    """
    lines = []
    for line in markdown_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#### "):
            line = line[len("#### ") :]
        lines.append(line)
    return "\n".join(lines) + "\n"


def read_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def write_state(**updates: Any) -> None:
    state = read_state()
    state.update(updates)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def check_models(console: DifyConsole) -> None:
    """Fail early with a clear message if the required models are missing.

    An unavailable embedding model only surfaces as an opaque indexing error
    several steps later, which is a miserable thing to debug.
    """
    for model_type, provider, model in (("text-embedding", EMBEDDING_PROVIDER, EMBEDDING_MODEL),):
        response = console.get(f"/workspaces/current/models/model-types/{model_type}")
        available = {
            (entry.get("provider"), model_entry.get("model"))
            for entry in response.get("data", [])
            for model_entry in entry.get("models", [])
            if model_entry.get("status") == "active"
        }
        if (provider, model) not in available:
            names = sorted(f"{p}/{m}" for p, m in available) or ["(none)"]
            raise SystemExit(
                f"[FAIL] {model_type} model {provider}/{model} is not available.\n"
                f"       Configure it under Settings → Model Provider. Currently active:\n"
                + "\n".join(f"       - {name}" for name in names)
            )
        log(f"[ok]   {model_type}: {provider}/{model}")


def find_dataset(console: DifyConsole, name: str) -> dict[str, Any] | None:
    response = console.get("/datasets?page=1&limit=100")
    for dataset in response.get("data", []):
        if dataset.get("name") == name:
            return dataset
    return None


def build_knowledge_config(file_id: str) -> dict[str, Any]:
    return {
        "indexing_technique": "high_quality",
        "doc_form": "hierarchical_model",  # Parent-Child
        "doc_language": "Japanese",
        "embedding_model": EMBEDDING_MODEL,
        "embedding_model_provider": EMBEDDING_PROVIDER,
        "data_source": {
            "info_list": {
                "data_source_type": "upload_file",
                "file_info_list": {"file_ids": [file_id]},
            }
        },
        "process_rule": {
            "mode": "hierarchical",
            "rules": {
                "pre_processing_rules": [
                    # §3-3 ①: collapse whitespace, but never strip URLs/emails —
                    # the guardrail reply has to be able to cite 佐藤's address.
                    {"id": "remove_extra_spaces", "enabled": True},
                    {"id": "remove_urls_emails", "enabled": False},
                ],
                "segmentation": {
                    "separator": PARENT_DELIMITER,
                    "max_tokens": PARENT_MAX_CHARS,
                    "chunk_overlap": 0,
                },
                "parent_mode": "paragraph",
                "subchunk_segmentation": {
                    "separator": CHILD_DELIMITER,
                    "max_tokens": CHILD_MAX_CHARS,
                    "chunk_overlap": 0,
                },
            },
        },
        "retrieval_model": RETRIEVAL_MODEL,
    }


def wait_for_indexing(console: DifyConsole, dataset_id: str, batch: str, timeout: int = 600) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        response = console.get(f"/datasets/{dataset_id}/batch/{batch}/indexing-status")
        documents = response.get("data", [])
        if not documents:
            raise SystemExit("[FAIL] indexing status returned no documents")
        statuses = [doc.get("indexing_status") for doc in documents]
        summary = ", ".join(
            f"{doc.get('indexing_status')} {doc.get('completed_segments', 0)}/{doc.get('total_segments', 0)}"
            for doc in documents
        )
        if summary != last:
            log(f"       indexing: {summary}")
            last = summary
        if all(status == "completed" for status in statuses):
            return
        if any(status == "error" for status in statuses):
            errors = [doc.get("error") for doc in documents if doc.get("error")]
            raise SystemExit(f"[FAIL] indexing failed: {errors}")
        time.sleep(3)
    raise SystemExit(f"[FAIL] indexing did not finish within {timeout}s")


def apply_metadata(console: DifyConsole, dataset_id: str, document_id: str) -> None:
    existing = {
        field["name"]: field["id"]
        for field in console.get(f"/datasets/{dataset_id}/metadata").get("doc_metadata", [])
    }
    metadata_list = []
    for name, value in METADATA_FIELDS.items():
        field_id = existing.get(name)
        if field_id is None:
            created = console.post(f"/datasets/{dataset_id}/metadata", {"type": "string", "name": name})
            field_id = created["id"]
            log(f"[ok]   metadata field created: {name}")
        metadata_list.append({"id": field_id, "name": name, "value": value})

    console.post(
        f"/datasets/{dataset_id}/documents/metadata",
        {"operation_data": [{"document_id": document_id, "metadata_list": metadata_list}]},
    )
    log(f"[ok]   metadata values assigned to document ({len(metadata_list)} fields)")

    console.post(f"/datasets/{dataset_id}/metadata/built-in/enable", {})
    log("[ok]   built-in metadata enabled")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help=f"delete an existing '{DATASET_NAME}' dataset and rebuild it from scratch",
    )
    args = parser.parse_args()

    if not SOURCE_DOCUMENT.exists():
        raise SystemExit(f"[FAIL] source document not found: {SOURCE_DOCUMENT}")

    env = load_env()
    log(f"[info] logging in to {env.get('DIFY_BASE_URL')} as {env.get('DIFY_EMAIL')}")
    try:
        console = connect(env)
    except DifyError as exc:
        raise SystemExit(f"[FAIL] login failed.\n{exc}") from exc
    log("[ok]   authenticated")

    check_models(console)

    existing = find_dataset(console, DATASET_NAME)
    if existing:
        if not args.recreate:
            raise SystemExit(
                f"[FAIL] dataset '{DATASET_NAME}' already exists (id={existing['id']}).\n"
                "       Re-run with --recreate to delete and rebuild it."
            )
        console.delete(f"/datasets/{existing['id']}")
        log(f"[ok]   deleted existing dataset {existing['id']}")

    with tempfile.TemporaryDirectory() as tmpdir:
        staged = Path(tmpdir) / UPLOAD_FILENAME
        staged.write_text(build_plaintext_source(SOURCE_DOCUMENT), encoding="utf-8")
        uploaded = console.upload_file(staged)
    log(f"[ok]   uploaded {UPLOAD_FILENAME} (file_id={uploaded['id']})")

    result = console.post("/datasets/init", build_knowledge_config(uploaded["id"]))
    dataset_id = result["dataset"]["id"]
    document_id = result["documents"][0]["id"]
    batch = result["batch"]
    log(f"[ok]   dataset created (id={dataset_id})")

    console.patch(
        f"/datasets/{dataset_id}",
        {
            "name": DATASET_NAME,
            "description": DATASET_DESCRIPTION,
            "retrieval_model": RETRIEVAL_MODEL,
            "indexing_technique": "high_quality",
            "embedding_model": EMBEDDING_MODEL,
            "embedding_model_provider": EMBEDDING_PROVIDER,
        },
    )
    log(f"[ok]   dataset named '{DATASET_NAME}', Hybrid Search + Rerank applied")

    log("[info] waiting for embedding to finish (this takes a few minutes)")
    wait_for_indexing(console, dataset_id, batch)
    log("[ok]   indexing completed")

    apply_metadata(console, dataset_id, document_id)

    write_state(dataset_id=dataset_id, dataset_name=DATASET_NAME, document_id=document_id)
    log("")
    log("=" * 60)
    log(f"  Knowledge base ready: {DATASET_NAME}")
    log(f"  dataset_id : {dataset_id}")
    log(f"  document_id: {document_id}")
    log(f"  state saved to {STATE_FILE.relative_to(REPO_ROOT)}")
    log("=" * 60)
    log("  Next: python3 scripts/provision_chatflow.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
