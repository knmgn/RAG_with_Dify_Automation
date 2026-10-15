"""Client for Dify's public Service API (`/v1/chat-messages`).

This is the same path a production integration uses, and the same one
scripts/test_e2e.py drives, so the bridge exercises exactly what was measured.
Standard library only, like the rest of the repository's Dify tooling.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class DifyAPIError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"Dify Service API returned HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class Citation:
    document_name: str
    # First line of the retrieved parent chunk, e.g. "第5条（タクシー代の支給要件）".
    # Parents are cut on article headings (§3-3 ①), so this is the article title.
    clause: str
    score: float


@dataclass(frozen=True)
class DifyAnswer:
    answer: str
    conversation_id: str
    citations: list[Citation] = field(default_factory=list)


def _citations(metadata: dict[str, Any]) -> list[Citation]:
    seen: set[str] = set()
    result: list[Citation] = []
    for resource in metadata.get("retriever_resources") or []:
        content = (resource.get("content") or "").strip()
        clause = content.splitlines()[0][:60] if content else ""
        if clause in seen:
            continue
        seen.add(clause)
        result.append(
            Citation(
                document_name=resource.get("document_name") or resource.get("dataset_name") or "",
                clause=clause,
                score=float(resource.get("score") or 0.0),
            )
        )
    return result


class DifyClient:
    def __init__(self, api_base: str, api_key: str, timeout: float = 120.0) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def ask(self, query: str, user: str, conversation_id: str | None = None) -> DifyAnswer:
        payload: dict[str, Any] = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "user": user,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        data = self._post("/chat-messages", payload)
        return DifyAnswer(
            answer=data.get("answer", ""),
            conversation_id=data.get("conversation_id", ""),
            citations=_citations(data.get("metadata") or {}),
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.api_base}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise DifyAPIError(error.code, error.read().decode("utf-8", "replace")) from error
