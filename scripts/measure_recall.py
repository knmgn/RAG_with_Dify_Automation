#!/usr/bin/env python3
"""Measure Recall@K on the knowledge base using the §3-4 test queries.

Runs the ten in-scope queries from the design doc plus a set of out-of-scope
queries (the "Do I get an allowance if I adopt a cat?" case from demo Scene 3),
and reports both recall and the score distribution. The score gap between the two sets is
what a Score Threshold has to separate, so this is also how SCORE_THRESHOLD in
provision_knowledge.py was chosen.

    python3 scripts/measure_recall.py
    python3 scripts/measure_recall.py --top-k 4 --threshold 0.01
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from dify_console import REPO_ROOT, DifyConsole, connect, load_env
from provision_knowledge import RETRIEVAL_WEIGHTS

STATE_FILE = REPO_ROOT / "scripts" / ".provision_state.json"

# §3-4 — query, and the article that must appear in the top K.
TEST_QUERIES: list[tuple[str, str]] = [
    ("How much can I claim for a late-night ride home?", "Article 5"),
    ("Can I take a taxi with a client?", "Article 5"),
    ("My rideshare went over the cap", "Article 5"),
    ("When is the expense report deadline?", "Article 8"),
    ("Where is template v3?", "Article 9"),
    ("I missed the 25th", "Article 8"),
    ("I lost my insurance card", "Article 15"),
    ("How much is the night shift differential?", "Article 13"),
    ("When do I need to request a night shift?", "Article 14"),
    ("Can I fly business class?", "Article 4"),
]

# Questions the policy genuinely does not answer. The bot must decline
# rather than improvise — see the guardrail rules in §1-2.
OUT_OF_SCOPE_QUERIES = [
    "Do I get an allowance if I adopt a cat?",
    "How many vacation days do I get?",
    "How is severance pay calculated?",
    "What's the weather in New York today?",
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


_ARTICLE = re.compile(r"^(Article \d+)\b")


def clause_of(record: dict[str, Any]) -> str:
    """The article a parent chunk belongs to, e.g. "Article 5".

    Parents are cut on article headings (§3-3 ①), so each one starts with
    "Article N (...)". Matching the whole token keeps "Article 15" from
    counting as a hit for "Article 1" or "Article 5".
    """
    content = record.get("segment", {}).get("content", "").lstrip()
    match = _ARTICLE.match(content)
    return match.group(1) if match else content[:20]


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
