"""Block Kit builders and Markdown → Slack mrkdwn conversion. Pure functions."""

from __future__ import annotations

import re
from typing import Any

from dify_client import Citation
from messages import t

# Slack rejects section text over 3,000 characters; leave room for escaping.
SECTION_LIMIT = 2900

ACTION_REPLY = "escalation_reply"
ACTION_RESOLVE = "escalation_resolve"
VIEW_REPLY = "escalation_reply_submit"

_MENTION = re.compile(r"<@[A-Z0-9]+(?:\|[^>]*)?>")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def strip_mentions(text: str) -> str:
    return _MENTION.sub("", text).strip()


def to_mrkdwn(text: str) -> str:
    """Escape Slack control characters and convert Markdown **bold** to *bold*.

    Escaping matters: Dify output is untrusted text, and an unescaped "<!channel>"
    or "<@U…>" in it would ping people. URLs still auto-link after escaping.
    """
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _BOLD.sub(r"*\1*", escaped)


def split_sections(text: str, limit: int = SECTION_LIMIT) -> list[str]:
    """Split on paragraph boundaries so each piece fits one section block."""
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks or [""]


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(*texts: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text} for text in texts]}


def answer_blocks(
    answer: str, citations: list[Citation], language: str, escalated: bool = False
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [_section(chunk) for chunk in split_sections(to_mrkdwn(answer))]
    if citations:
        lines = [
            f"📄 {to_mrkdwn(c.clause or c.document_name)} · {t(language, 'score')} {c.score:.2f}"
            for c in citations
        ]
        blocks.append(_context(f"*{t(language, 'sources')}*", *lines[:9]))
    if escalated:
        blocks.append(_section(t(language, "escalated_notice")))
    blocks.append(_context(t(language, "bot_label")))
    return blocks


def escalation_blocks(
    escalation_id: str,
    asker: str,
    question: str,
    permalink: str,
    language: str,
    status_line: str | None = None,
) -> list[dict[str, Any]]:
    quoted = "\n".join(f"> {line}" for line in to_mrkdwn(question).splitlines() or [""])
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": t(language, "escalation_header")}},
        _section(
            f"*{t(language, 'asked_by')}:* <@{asker}>\n*{t(language, 'question')}:*\n{quoted[:2500]}"
        ),
    ]
    if permalink:
        blocks.append(_context(f"<{permalink}|{t(language, 'open_thread')}>"))
    if status_line:
        blocks.append(_context(status_line))
    else:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": ACTION_REPLY,
                        "style": "primary",
                        "text": {"type": "plain_text", "text": t(language, "reply_button")},
                        "value": escalation_id,
                    },
                    {
                        "type": "button",
                        "action_id": ACTION_RESOLVE,
                        "text": {"type": "plain_text", "text": t(language, "resolve_button")},
                        "value": escalation_id,
                    },
                ],
            }
        )
    return blocks


def reply_modal(escalation_id: str, question: str, language: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": VIEW_REPLY,
        "private_metadata": escalation_id,
        "title": {"type": "plain_text", "text": t(language, "modal_title")[:24]},
        "submit": {"type": "plain_text", "text": t(language, "modal_submit")},
        "blocks": [
            _section("\n".join(f"> {line}" for line in to_mrkdwn(question).splitlines() or [""])[:2900]),
            {
                "type": "input",
                "block_id": "answer",
                "label": {"type": "plain_text", "text": t(language, "modal_label")},
                "hint": {"type": "plain_text", "text": t(language, "modal_hint")},
                "element": {"type": "plain_text_input", "action_id": "text", "multiline": True},
            },
        ],
    }


def human_answer_blocks(owner: str, text: str, language: str) -> list[dict[str, Any]]:
    blocks = [_section(f"*{t(language, 'human_answer_header', owner=f'<@{owner}>')}*")]
    blocks += [_section(chunk) for chunk in split_sections(to_mrkdwn(text))]
    blocks.append(_context(t(language, "human_answer_note")))
    return blocks
