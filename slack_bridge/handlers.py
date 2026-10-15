"""Slack event and interaction handlers.

Kept free of Bolt specifics: each method takes the Slack event/body and a
WebClient-like `client`, so the tests can drive them with a fake client.
app.py wires them to Bolt listeners.

Flow:
  question (mention or DM) → Dify Service API → threaded answer with sources
  └ guardrail fired (fixed refusal) → escalation card in the owner channel
      ├ "Reply in thread" → modal → the owner's answer is posted in the
      │                      employee's thread under the owner's own name and
      │                      profile photo, labelled as human-written
      └ "Mark resolved"   → card closed without a reply
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from config import Config
from dify_client import DifyClient
from formatting import (
    answer_blocks,
    escalation_blocks,
    human_answer_blocks,
    reply_modal,
    strip_mentions,
)
from messages import t
from store import ConversationStore, Escalation

log = logging.getLogger(__name__)

WORKING_REACTION = "hourglass_flowing_sand"


class Bridge:
    def __init__(self, config: Config, dify: DifyClient, store: ConversationStore) -> None:
        self.config = config
        self.dify = dify
        self.store = store
        self.lang = config.ui_language

    # ── questions ───────────────────────────────────────────────────────

    def handle_question(self, event: dict[str, Any], client: Any) -> None:
        # Ignore edits, joins, and anything a bot posted (including our own replies).
        if event.get("subtype") or event.get("bot_id"):
            return

        channel = event["channel"]
        user = event["user"]
        thread_ts = event.get("thread_ts") or event["ts"]
        question = strip_mentions(event.get("text", ""))

        if not question:
            client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=t(self.lang, "empty_question"))
            return

        self._react(client, "reactions_add", channel, event["ts"])
        try:
            self._answer(client, channel, thread_ts, user, question)
        finally:
            self._react(client, "reactions_remove", channel, event["ts"])

    def _answer(self, client: Any, channel: str, thread_ts: str, user: str, question: str) -> None:
        try:
            result = self.dify.ask(
                question,
                # Dify keys conversation logs by this value; the Slack user ID is
                # stable and needs no lookup (04_api_examples.md §9).
                user=f"slack-{user}",
                conversation_id=self.store.get(channel, thread_ts),
            )
        except Exception:
            log.exception("Dify request failed for channel=%s thread=%s", channel, thread_ts)
            client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=t(self.lang, "error"))
            return

        if result.conversation_id:
            self.store.put(channel, thread_ts, result.conversation_id)

        refused = self.config.fallback_marker in result.answer
        escalated = refused and self._escalate(client, channel, thread_ts, user, question)

        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=result.answer[:3000],
            # A refusal cites nothing by construction; any retrieved chunks were
            # judged irrelevant by the guardrail, so don't present them as sources.
            blocks=answer_blocks(result.answer, [] if refused else result.citations, self.lang, escalated),
            unfurl_links=False,
        )

    def _escalate(self, client: Any, channel: str, thread_ts: str, user: str, question: str) -> bool:
        """Post an escalation card. Returns False (and the employee is not told
        a person will reply) if escalation is disabled or the post fails."""
        if not self.config.escalation_channel:
            return False
        try:
            permalink = client.chat_getPermalink(channel=channel, message_ts=thread_ts)["permalink"]
        except Exception:
            log.warning("could not get a permalink for %s/%s", channel, thread_ts, exc_info=True)
            permalink = ""

        escalation_id = uuid.uuid4().hex
        self.store.create_escalation(escalation_id, channel, thread_ts, user, question, permalink)
        try:
            response = client.chat_postMessage(
                channel=self.config.escalation_channel,
                text=t(self.lang, "escalation_header"),
                blocks=escalation_blocks(escalation_id, user, question, permalink, self.lang),
                unfurl_links=False,
            )
        except Exception:
            log.exception("could not post to escalation channel %s", self.config.escalation_channel)
            self.store.close_escalation(escalation_id, "failed", "")
            return False
        self.store.set_escalation_message(escalation_id, response["channel"], response["ts"])
        return True

    # ── escalation interactions ─────────────────────────────────────────

    def open_reply_modal(self, body: dict[str, Any], client: Any) -> None:
        escalation = self._open_escalation(body, client)
        if escalation:
            client.views_open(
                trigger_id=body["trigger_id"],
                view=reply_modal(escalation.id, escalation.question, self.lang),
            )

    def resolve(self, body: dict[str, Any], client: Any) -> None:
        escalation_id = body["actions"][0]["value"]
        owner = body["user"]["id"]
        if not self.store.close_escalation(escalation_id, "resolved", owner):
            self._tell(client, body, t(self.lang, "already_handled"))
            return
        self._close_card(client, escalation_id, t(self.lang, "status_resolved", owner=f"<@{owner}>"))

    def submit_reply(self, body: dict[str, Any], view: dict[str, Any], client: Any, ack: Callable[..., Any]) -> None:
        text = (view["state"]["values"]["answer"]["text"].get("value") or "").strip()
        if not text:
            ack(response_action="errors", errors={"answer": t(self.lang, "empty_question")})
            return
        ack()

        escalation_id = view["private_metadata"]
        owner = body["user"]["id"]
        # Claim first so two owners answering at once cannot both post.
        if not self.store.close_escalation(escalation_id, "answered", owner):
            client.chat_postMessage(channel=owner, text=t(self.lang, "already_handled"))
            return

        escalation = self.store.get_escalation(escalation_id)
        assert escalation is not None
        message = {
            "channel": escalation.channel,
            "thread_ts": escalation.thread_ts,
            "text": text[:3000],
            "blocks": human_answer_blocks(owner, text, self.lang),
        }
        identity = self._owner_identity(client, owner)
        try:
            try:
                client.chat_postMessage(**message, **identity)
            except Exception:
                if not identity:
                    raise
                # e.g. chat:write.customize not granted yet: post under the bot's
                # own name instead. The header and note still say who wrote it.
                log.warning("posting as %s failed; falling back to the bot identity", owner, exc_info=True)
                client.chat_postMessage(**message)
        except Exception:
            # Give the claim back so the card's buttons keep working.
            self.store.reopen_escalation(escalation_id)
            raise
        self._close_card(client, escalation_id, t(self.lang, "status_answered", owner=f"<@{owner}>"))

    # ── helpers ─────────────────────────────────────────────────────────

    def _open_escalation(self, body: dict[str, Any], client: Any) -> Escalation | None:
        escalation = self.store.get_escalation(body["actions"][0]["value"])
        if escalation is None or escalation.status != "open":
            self._tell(client, body, t(self.lang, "already_handled"))
            return None
        return escalation

    def _close_card(self, client: Any, escalation_id: str, status_line: str) -> None:
        escalation = self.store.get_escalation(escalation_id)
        if escalation is None or not escalation.escalation_ts:
            return
        client.chat_update(
            channel=escalation.escalation_channel,
            ts=escalation.escalation_ts,
            text=t(self.lang, "escalation_header"),
            blocks=escalation_blocks(
                escalation.id,
                escalation.asker,
                escalation.question,
                escalation.permalink,
                self.lang,
                status_line=status_line,
            ),
        )

    @staticmethod
    def _owner_identity(client: Any, owner: str) -> dict[str, str]:
        """The owner's Slack name and profile photo, to post their answer under.

        AI answers show the bot's icon; human answers show the person's face, so
        the thread itself makes clear which is which. Slack still marks the
        message with an APP badge, so it cannot pass for a message the owner
        typed directly. Returns {} if the profile cannot be read (users:read
        missing, deactivated user), in which case the bot identity is used.
        """
        try:
            profile = client.users_info(user=owner)["user"]["profile"]
        except Exception:
            log.warning("could not read profile of %s", owner, exc_info=True)
            return {}
        name = (profile.get("display_name") or profile.get("real_name") or "").strip()
        icon = profile.get("image_192") or profile.get("image_72") or ""
        identity: dict[str, str] = {}
        if name:
            identity["username"] = name
        if icon:
            identity["icon_url"] = icon
        return identity

    @staticmethod
    def _tell(client: Any, body: dict[str, Any], text: str) -> None:
        client.chat_postEphemeral(channel=body["channel"]["id"], user=body["user"]["id"], text=text)

    @staticmethod
    def _react(client: Any, method: str, channel: str, ts: str) -> None:
        # Cosmetic progress indicator; never let it break answering.
        try:
            getattr(client, method)(channel=channel, timestamp=ts, name=WORKING_REACTION)
        except Exception:
            log.debug("%s failed", method, exc_info=True)
