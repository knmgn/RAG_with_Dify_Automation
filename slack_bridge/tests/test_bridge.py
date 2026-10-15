"""Unit tests for the Slack bridge. No Slack or Dify needed.

    cd slack_bridge && python3 -m unittest -v
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ConfigError, load_config  # noqa: E402
from dify_client import Citation, DifyAnswer, DifyClient  # noqa: E402
from formatting import ACTION_REPLY, ACTION_RESOLVE, split_sections, strip_mentions, to_mrkdwn  # noqa: E402
from handlers import Bridge  # noqa: E402
from store import ConversationStore  # noqa: E402

# Failure-path tests log tracebacks on purpose; keep the output readable.
logging.disable(logging.CRITICAL)

REFUSAL = (
    "ご質問の件について、社内規程（DL-HR-RG-2024-007）内に明示的な記載が見当たりませんでした。"
    "詳細については総務部の佐藤（内線1234）まで直接お問い合わせください。"
)
TAXI_ANSWER = "【結論】\n深夜帰宅時のタクシー代は、1回あたり**15,000円（消費税込）**が上限です。"

ENV = {
    "SLACK_BOT_TOKEN": "xoxb-test",
    "SLACK_APP_TOKEN": "xapp-test",
    "DIFY_API_KEY": "app-test",
    "SLACK_ESCALATION_CHANNEL": "C_OWNERS",
    "BRIDGE_DB_PATH": ":memory:",
}


class FakeSlack:
    """Records WebClient calls; returns minimal plausible responses."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail or set()
        self._ts = 100

    def __getattr__(self, method: str):
        def call(**kwargs: Any) -> dict[str, Any]:
            self.calls.append((method, kwargs))
            if method in self.fail:
                raise RuntimeError(f"{method} failed")
            if method == "chat_postMessage":
                self._ts += 1
                return {"ok": True, "channel": kwargs["channel"], "ts": f"{self._ts}.000"}
            if method == "chat_getPermalink":
                return {"ok": True, "permalink": "https://slack.example/archives/C1/p1"}
            if method == "users_info":
                return {"ok": True, "user": {"id": kwargs["user"], "profile": {
                    "display_name": "佐藤 健一", "real_name": "Kenichi Sato",
                    "image_192": "https://avatars.slack.example/sato_192.png"}}}
            return {"ok": True}

        return call

    def posts(self, channel: str | None = None) -> list[dict[str, Any]]:
        return [k for m, k in self.calls if m == "chat_postMessage" and (channel is None or k["channel"] == channel)]

    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]


class FakeDify:
    def __init__(self, answers: list[DifyAnswer] | None = None, error: Exception | None = None) -> None:
        self.answers = answers or []
        self.error = error
        self.requests: list[dict[str, Any]] = []

    def ask(self, query: str, user: str, conversation_id: str | None = None) -> DifyAnswer:
        self.requests.append({"query": query, "user": user, "conversation_id": conversation_id})
        if self.error:
            raise self.error
        return self.answers.pop(0)


def make_bridge(dify: FakeDify, **env: str) -> Bridge:
    config = load_config({**ENV, **env})
    return Bridge(config, dify, ConversationStore(":memory:"))  # type: ignore[arg-type]


def mention(text: str, ts: str = "1.000", thread_ts: str | None = None) -> dict[str, Any]:
    event = {"type": "app_mention", "channel": "C1", "user": "U_EMP", "text": text, "ts": ts}
    if thread_ts:
        event["thread_ts"] = thread_ts
    return event


def all_text(blocks: list[dict[str, Any]]) -> str:
    return json.dumps(blocks, ensure_ascii=False)


class QuestionTests(unittest.TestCase):
    def test_answers_in_thread_with_sources(self) -> None:
        citation = Citation("DL-HR-RG-2024-007.txt", "第5条（タクシー代の支給要件）", 0.6438)
        dify = FakeDify([DifyAnswer(TAXI_ANSWER, "conv-1", [citation])])
        slack = FakeSlack()
        make_bridge(dify).handle_question(mention("<@UBOT> 深夜帰りのタクシー代いくら？"), slack)

        self.assertEqual(dify.requests[0]["query"], "深夜帰りのタクシー代いくら？")
        self.assertEqual(dify.requests[0]["user"], "slack-U_EMP")
        [reply] = slack.posts()
        self.assertEqual(reply["thread_ts"], "1.000")
        blocks = all_text(reply["blocks"])
        self.assertIn("*15,000円（消費税込）*", blocks)
        self.assertIn("第5条（タクシー代の支給要件）", blocks)
        self.assertIn("0.64", blocks)
        self.assertNotIn("chat_update", slack.methods())

    def test_follow_up_in_thread_reuses_conversation(self) -> None:
        dify = FakeDify([DifyAnswer(TAXI_ANSWER, "conv-1"), DifyAnswer("【結論】\n必要です。", "conv-1")])
        bridge = make_bridge(dify)
        bridge.handle_question(mention("<@UBOT> タクシー代は？", ts="1.000"), FakeSlack())
        bridge.handle_question(mention("<@UBOT> それって領収書いる？", ts="2.000", thread_ts="1.000"), FakeSlack())
        self.assertIsNone(dify.requests[0]["conversation_id"])
        self.assertEqual(dify.requests[1]["conversation_id"], "conv-1")

    def test_new_top_level_question_starts_fresh(self) -> None:
        dify = FakeDify([DifyAnswer(TAXI_ANSWER, "conv-1"), DifyAnswer(TAXI_ANSWER, "conv-2")])
        bridge = make_bridge(dify)
        bridge.handle_question(mention("<@UBOT> a", ts="1.000"), FakeSlack())
        bridge.handle_question(mention("<@UBOT> b", ts="2.000"), FakeSlack())
        self.assertIsNone(dify.requests[1]["conversation_id"])

    def test_ignores_bot_messages_and_edits(self) -> None:
        dify = FakeDify()
        bridge = make_bridge(dify)
        slack = FakeSlack()
        bridge.handle_question({**mention("hi"), "bot_id": "B1"}, slack)
        bridge.handle_question({**mention("hi"), "subtype": "message_changed"}, slack)
        self.assertEqual(slack.calls, [])
        self.assertEqual(dify.requests, [])

    def test_empty_question_is_not_sent_to_dify(self) -> None:
        dify = FakeDify()
        slack = FakeSlack()
        make_bridge(dify).handle_question(mention("<@UBOT>"), slack)
        self.assertEqual(dify.requests, [])
        self.assertEqual(len(slack.posts()), 1)

    def test_dify_failure_tells_the_user_and_clears_reaction(self) -> None:
        slack = FakeSlack()
        make_bridge(FakeDify(error=OSError("connection refused"))).handle_question(mention("<@UBOT> q"), slack)
        [reply] = slack.posts()
        self.assertIn("エラー", reply["text"])
        self.assertEqual(slack.methods()[-1], "reactions_remove")

    def test_reaction_failure_does_not_block_answer(self) -> None:
        slack = FakeSlack(fail={"reactions_add", "reactions_remove"})
        make_bridge(FakeDify([DifyAnswer(TAXI_ANSWER, "c")])).handle_question(mention("<@UBOT> q"), slack)
        self.assertEqual(len(slack.posts()), 1)


class EscalationTests(unittest.TestCase):
    def refuse(self, slack: FakeSlack, **env: str) -> Bridge:
        # Retrieved chunks on a refusal must not be shown as sources.
        stray = Citation("doc.txt", "第13条（夜勤手当）", 0.31)
        bridge = make_bridge(FakeDify([DifyAnswer(REFUSAL, "conv-9", [stray])]), **env)
        bridge.handle_question(mention("<@UBOT> 猫を飼ったら手当出る？"), slack)
        return bridge

    def card_id(self, slack: FakeSlack) -> str:
        [card] = slack.posts("C_OWNERS")
        [actions] = [b for b in card["blocks"] if b["type"] == "actions"]
        return actions["elements"][0]["value"]

    def test_refusal_posts_card_and_tells_employee(self) -> None:
        slack = FakeSlack()
        self.refuse(slack)
        [card] = slack.posts("C_OWNERS")
        self.assertIn("<@U_EMP>", all_text(card["blocks"]))
        self.assertIn("猫を飼ったら手当出る？", all_text(card["blocks"]))
        self.assertIn("https://slack.example/archives/C1/p1", all_text(card["blocks"]))
        [reply] = slack.posts("C1")
        self.assertIn("担当者に共有しました", all_text(reply["blocks"]))
        self.assertNotIn("第13条", all_text(reply["blocks"]))

    def test_no_escalation_channel_means_no_card_and_no_promise(self) -> None:
        slack = FakeSlack()
        self.refuse(slack, SLACK_ESCALATION_CHANNEL="")
        self.assertEqual(slack.posts("C_OWNERS"), [])
        self.assertNotIn("担当者に共有しました", all_text(slack.posts("C1")[0]["blocks"]))

    def test_failed_card_post_does_not_promise_a_human(self) -> None:
        class FailOwnerChannel(FakeSlack):
            def __getattr__(self, method: str):
                inner = super().__getattr__(method)

                def call(**kwargs: Any) -> dict[str, Any]:
                    if method == "chat_postMessage" and kwargs["channel"] == "C_OWNERS":
                        self.calls.append((method, kwargs))
                        raise RuntimeError("not_in_channel")
                    return inner(**kwargs)

                return call

        slack = FailOwnerChannel()
        self.refuse(slack)
        [reply] = [k for m, k in slack.calls if m == "chat_postMessage" and k["channel"] == "C1"]
        self.assertNotIn("担当者に共有しました", all_text(reply["blocks"]))

    def test_owner_reply_lands_in_employee_thread(self) -> None:
        slack = FakeSlack()
        bridge = self.refuse(slack)
        escalation_id = self.card_id(slack)

        body = {"actions": [{"value": escalation_id}], "trigger_id": "T1",
                "user": {"id": "U_SATO"}, "channel": {"id": "C_OWNERS"}}
        bridge.open_reply_modal(body, slack)
        [(_, opened)] = [(m, k) for m, k in slack.calls if m == "views_open"]
        self.assertEqual(opened["view"]["private_metadata"], escalation_id)

        acks: list[dict[str, Any]] = []
        view = {"private_metadata": escalation_id,
                "state": {"values": {"answer": {"text": {"value": "ペット手当の制度はありません。"}}}}}
        bridge.submit_reply({"user": {"id": "U_SATO"}}, view, slack, lambda **kw: acks.append(kw))
        self.assertEqual(acks, [{}])

        human = slack.posts("C1")[-1]
        self.assertEqual(human["thread_ts"], "1.000")
        self.assertIn("<@U_SATO>", all_text(human["blocks"]))
        self.assertIn("AIによる生成ではありません", all_text(human["blocks"]))

        [(_, update)] = [(m, k) for m, k in slack.calls if m == "chat_update"]
        self.assertEqual(update["channel"], "C_OWNERS")
        self.assertFalse([b for b in update["blocks"] if b["type"] == "actions"])
        self.assertIn("回答しました", all_text(update["blocks"]))

    def answer(self, bridge: Bridge, slack: FakeSlack, owner: str = "U_SATO") -> None:
        view = {"private_metadata": self.card_id(slack),
                "state": {"values": {"answer": {"text": {"value": "ペット手当の制度はありません。"}}}}}
        bridge.submit_reply({"user": {"id": owner}}, view, slack, lambda **kw: None)

    def test_owner_reply_uses_owner_name_and_photo(self) -> None:
        slack = FakeSlack()
        bridge = self.refuse(slack)
        self.answer(bridge, slack)
        human = slack.posts("C1")[-1]
        self.assertEqual(human["username"], "佐藤 健一")
        self.assertEqual(human["icon_url"], "https://avatars.slack.example/sato_192.png")
        # The bot's own answers keep the bot identity.
        self.assertNotIn("username", slack.posts("C1")[0])

    def test_falls_back_to_real_name_without_display_name(self) -> None:
        class NoDisplayName(FakeSlack):
            def __getattr__(self, method: str):
                if method != "users_info":
                    return super().__getattr__(method)
                return lambda **kw: {"ok": True, "user": {"profile": {"display_name": "", "real_name": "Kenichi Sato"}}}

        slack = NoDisplayName()
        bridge = self.refuse(slack)
        self.answer(bridge, slack)
        human = slack.posts("C1")[-1]
        self.assertEqual(human["username"], "Kenichi Sato")
        self.assertNotIn("icon_url", human)

    def test_unreadable_profile_posts_as_bot(self) -> None:
        slack = FakeSlack(fail={"users_info"})
        bridge = self.refuse(slack)
        self.answer(bridge, slack)
        human = slack.posts("C1")[-1]
        self.assertNotIn("username", human)
        self.assertIn("AIによる生成ではありません", all_text(human["blocks"]))
        self.assertEqual(bridge.store.get_escalation(self.card_id(slack)).status, "answered")

    def test_rejected_customization_retries_as_bot(self) -> None:
        class RejectCustomization(FakeSlack):
            def __getattr__(self, method: str):
                inner = super().__getattr__(method)

                def call(**kwargs: Any) -> dict[str, Any]:
                    if method == "chat_postMessage" and "username" in kwargs:
                        self.calls.append((method, kwargs))
                        raise RuntimeError("missing_scope: chat:write.customize")
                    return inner(**kwargs)

                return call

        slack = RejectCustomization()
        bridge = self.refuse(slack)
        self.answer(bridge, slack)
        attempts = [k for m, k in slack.calls if m == "chat_postMessage" and k["channel"] == "C1"][1:]
        self.assertEqual(["username" in k for k in attempts], [True, False])
        self.assertEqual(bridge.store.get_escalation(self.card_id(slack)).status, "answered")
        self.assertIn("chat_update", slack.methods())

    def test_empty_reply_is_rejected_in_modal(self) -> None:
        slack = FakeSlack()
        bridge = self.refuse(slack)
        acks: list[dict[str, Any]] = []
        view = {"private_metadata": self.card_id(slack), "state": {"values": {"answer": {"text": {"value": "  "}}}}}
        bridge.submit_reply({"user": {"id": "U_SATO"}}, view, slack, lambda **kw: acks.append(kw))
        self.assertEqual(acks[0]["response_action"], "errors")

    def test_second_owner_cannot_answer_twice(self) -> None:
        slack = FakeSlack()
        bridge = self.refuse(slack)
        escalation_id = self.card_id(slack)
        view = {"private_metadata": escalation_id, "state": {"values": {"answer": {"text": {"value": "回答"}}}}}
        bridge.submit_reply({"user": {"id": "U_A"}}, view, slack, lambda **kw: None)
        bridge.submit_reply({"user": {"id": "U_B"}}, view, slack, lambda **kw: None)
        human_answers = [p for p in slack.posts("C1") if p.get("thread_ts") and "回答" == p["text"]]
        self.assertEqual(len(human_answers), 1)
        self.assertIn("すでに対応済み", slack.posts("U_B")[0]["text"])

    def test_failed_reply_post_reopens_the_card(self) -> None:
        slack = FakeSlack()
        bridge = self.refuse(slack)
        escalation_id = self.card_id(slack)
        slack.fail.add("chat_postMessage")
        view = {"private_metadata": escalation_id, "state": {"values": {"answer": {"text": {"value": "回答"}}}}}
        with self.assertRaises(RuntimeError):
            bridge.submit_reply({"user": {"id": "U_A"}}, view, slack, lambda **kw: None)
        self.assertEqual(bridge.store.get_escalation(escalation_id).status, "open")

    def test_resolve_closes_card(self) -> None:
        slack = FakeSlack()
        bridge = self.refuse(slack)
        body = {"actions": [{"value": self.card_id(slack), "action_id": ACTION_RESOLVE}],
                "user": {"id": "U_SATO"}, "channel": {"id": "C_OWNERS"}}
        bridge.resolve(body, slack)
        bridge.resolve(body, slack)
        self.assertEqual(len([m for m in slack.methods() if m == "chat_update"]), 1)
        self.assertIn("chat_postEphemeral", slack.methods())

    def test_reply_button_on_closed_card_is_refused(self) -> None:
        slack = FakeSlack()
        bridge = self.refuse(slack)
        body = {"actions": [{"value": self.card_id(slack), "action_id": ACTION_REPLY}], "trigger_id": "T",
                "user": {"id": "U_SATO"}, "channel": {"id": "C_OWNERS"}}
        bridge.resolve(body, slack)
        bridge.open_reply_modal(body, slack)
        self.assertNotIn("views_open", slack.methods())


class FormattingTests(unittest.TestCase):
    def test_escapes_slack_control_sequences(self) -> None:
        self.assertEqual(to_mrkdwn("<!channel> a & b"), "&lt;!channel&gt; a &amp; b")

    def test_converts_markdown_bold(self) -> None:
        self.assertEqual(to_mrkdwn("📎 **経費精算テンプレート_v3.xlsx**"), "📎 *経費精算テンプレート_v3.xlsx*")

    def test_strip_mentions(self) -> None:
        self.assertEqual(strip_mentions("<@U123ABC> 保険証なくした"), "保険証なくした")

    def test_split_sections_respects_limit(self) -> None:
        text = "\n\n".join(["あ" * 1000] * 5 + ["い" * 7000])
        chunks = split_sections(text, limit=2900)
        self.assertTrue(all(len(c) <= 2900 for c in chunks))
        self.assertEqual("".join(chunks).replace("\n", ""), text.replace("\n", ""))


class ConfigTests(unittest.TestCase):
    def test_rejects_swapped_tokens(self) -> None:
        with self.assertRaises(ConfigError):
            load_config({**ENV, "SLACK_BOT_TOKEN": "xapp-wrong"})

    def test_requires_dify_key(self) -> None:
        with self.assertRaises(ConfigError):
            load_config({k: v for k, v in ENV.items() if k != "DIFY_API_KEY"})


class DifyClientTests(unittest.TestCase):
    """Runs the real client against a local HTTP server standing in for Dify."""

    def setUp(self) -> None:
        received: list[dict[str, Any]] = []
        self.received = received

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append({"path": self.path, "auth": self.headers["Authorization"], "body": body})
                if body["query"] == "boom":
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"code":"internal_server_error"}')
                    return
                payload = {
                    "answer": TAXI_ANSWER,
                    "conversation_id": "conv-42",
                    "metadata": {"retriever_resources": [
                        {"document_name": "d.txt", "score": 0.64, "content": "第5条（タクシー代の支給要件）\n1. …"},
                        {"document_name": "d.txt", "score": 0.50, "content": "第5条（タクシー代の支給要件）\n4. …"},
                        {"document_name": "d.txt", "score": 0.41, "content": "第8条（提出期限）\n…"},
                    ]},
                }
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.client = DifyClient(f"http://127.0.0.1:{self.server.server_port}/v1", "app-key", timeout=5)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def test_request_shape_and_parsing(self) -> None:
        result = self.client.ask("タクシー代は？", user="slack-U1", conversation_id="conv-41")
        [request] = self.received
        self.assertEqual(request["path"], "/v1/chat-messages")
        self.assertEqual(request["auth"], "Bearer app-key")
        self.assertEqual(request["body"]["response_mode"], "blocking")
        self.assertEqual(request["body"]["conversation_id"], "conv-41")
        self.assertEqual(result.conversation_id, "conv-42")
        # Two chunks from the same article collapse into one source.
        self.assertEqual([c.clause for c in result.citations], ["第5条（タクシー代の支給要件）", "第8条（提出期限）"])

    def test_omits_conversation_id_on_first_turn(self) -> None:
        self.client.ask("q", user="u")
        self.assertNotIn("conversation_id", self.received[0]["body"])

    def test_http_error_raises(self) -> None:
        from dify_client import DifyAPIError

        with self.assertRaises(DifyAPIError) as caught:
            self.client.ask("boom", user="u")
        self.assertEqual(caught.exception.status, 500)


if __name__ == "__main__":
    unittest.main()
