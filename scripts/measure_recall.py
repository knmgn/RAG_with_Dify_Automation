#!/usr/bin/env python3
"""Measure Recall@K on the knowledge base using the §3-4 test queries.

Runs the ten in-scope queries from the design doc plus a set of out-of-scope
queries (the "猫を飼ったら手当出る？" case from demo Scene 3), and reports both
recall and the rerank score distribution. The score gap between the two sets is
what a Score Threshold has to separate, so this is also how SCORE_THRESHOLD in
provision_knowledge.py was chosen.

    python3 scripts/measure_recall.py
    python3 scripts/measure_recall.py --top-k 4 --threshold 0.01
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from dify_console import REPO_ROOT, DifyConsole, connect, load_env
from provision_knowledge import RETRIEVAL_WEIGHTS

STATE_FILE = REPO_ROOT / "scripts" / ".provision_state.json"

# §3-4 — query, and the clause that must appear in the top K.
TEST_QUERIES: list[tuple[str, str]] = [
    ("深夜帰りのタクシー代いくら？", "第5条"),
    ("クライアントとタクシー乗っていいの？", "第5条"),
    ("タクシー上限超えた", "第5条"),
    ("経費の締め切りいつ？", "第8条"),
    ("テンプレ v3 どこ？", "第9条"),
    ("25日過ぎちゃった", "第8条"),
    ("保険証なくした", "第15条"),
    ("夜勤手当いくら？", "第13条"),
    ("深夜シフトいつまでに申請？", "第14条"),
    ("新幹線グリーン車乗れる？", "第4条"),
]

# Questions the regulation genuinely does not answer. The bot must decline
# rather than improvise — see the guardrail rules in §1-2.
OUT_OF_SCOPE_QUERIES = [
    "猫を飼ったら手当出る？",
    "有給休暇は何日もらえますか？",
    "退職金の計算方法を教えて",
    "今日の東京の天気は？",
]


def retrieval_model(top_k: int, threshold: float | None) -> dict[str, Any]:
    """Same Hybrid Search + Weighted Score config the dataset is provisioned with."""
    return {
        "search_method": "hybrid_search",
        "reranking_enable": False,
        "reranking_mode": "weighted_score",
        "reranking_model": {"reranking_provider_name": "", "reranking_model_name": ""},
        "top_k": top_k,
        "score_threshold_enabled": threshold is not None,
        "score_threshold": threshold or 0.0,
        "weights": RETRIEVAL_WEIGHTS,
    }


def search(
    console: DifyConsole,
    dataset_id: str,
    query: str,
    model: dict[str, Any],
    delay: float,
) -> list[dict[str, Any]]:
    """One hit-test, optionally paced.

    Weighted Score reranking runs inside Weaviate, so there is no third-party
    rate limit to respect and the default delay is 0. The flag is kept because
    it is needed the moment anyone switches back to a hosted reranker: a trial
    Cohere key allows ~10 calls/min, and past that Dify swallows the 429 and
    returns *zero* records, which is indistinguishable from "the score
    threshold filtered everything out".
    """
    response = console.post(
        f"/datasets/{dataset_id}/hit-testing", {"query": query, "retrieval_model": model}
    )
    time.sleep(delay)
    return response.get("records", [])


def clause_of(record: dict[str, Any]) -> str:
    content = record.get("segment", {}).get("content", "").lstrip()
    return content[:12].split("（")[0].strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="seconds to wait between queries; only needed with a rate-limited hosted reranker",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="score threshold to apply; omit to retrieve unfiltered and just report scores",
    )
    args = parser.parse_args()

    if not STATE_FILE.exists():
        raise SystemExit("[FAIL] scripts/.provision_state.json not found. Run provision_knowledge.py first.")
    dataset_id = json.loads(STATE_FILE.read_text(encoding="utf-8"))["dataset_id"]

    console = connect(load_env())
    model = retrieval_model(args.top_k, args.threshold)

    print("=" * 72)
    print(f"  Recall@{args.top_k}  —  Hybrid Search + Weighted Score (semantic 0.7 / keyword 0.3)")
    print(f"  score threshold: {args.threshold if args.threshold is not None else 'off'}")
    print("=" * 72)

    hits = 0
    in_scope_top_scores: list[float] = []
    for query, expected in TEST_QUERIES:
        records = search(console, dataset_id, query, model, args.delay)
        clauses = [clause_of(record) for record in records]
        found = expected in clauses
        hits += found
        top = records[0].get("score", 0.0) if records else 0.0
        in_scope_top_scores.append(top)
        mark = "PASS" if found else "FAIL"
        print(f"  [{mark}] {query}")
        print(f"         expected {expected} | got {clauses or '(none)'} | top score {top:.4f}")

    recall = hits / len(TEST_QUERIES) * 100
    print("-" * 72)
    print(f"  Recall@{args.top_k} = {hits}/{len(TEST_QUERIES)} = {recall:.0f}%   (target: >= 90%)")

    print()
    print("  Out-of-scope queries (these should retrieve nothing useful):")
    out_top_scores: list[float] = []
    for query in OUT_OF_SCOPE_QUERIES:
        records = search(console, dataset_id, query, model, args.delay)
        top = records[0].get("score", 0.0) if records else 0.0
        out_top_scores.append(top)
        print(f"    {query} -> {len(records)} hits, top score {top:.4f}")

    print("-" * 72)
    if in_scope_top_scores and out_top_scores:
        print(f"  in-scope  top-score min : {min(in_scope_top_scores):.4f}")
        print(f"  out-of-scope top-score max: {max(out_top_scores):.4f}")
        print("  A usable Score Threshold sits between those two numbers.")
    print("=" * 72)

    return 0 if recall >= 90 else 1


if __name__ == "__main__":
    sys.exit(main())
