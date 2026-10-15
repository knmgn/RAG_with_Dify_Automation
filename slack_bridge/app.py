"""Entry point: connects Slack (Socket Mode) to the Dify Chatflow.

Socket Mode means the bridge opens an outbound WebSocket to Slack. Nothing has
to be exposed to the internet: no public URL, no tunnel, no inbound firewall
rule. That keeps the "nothing listens on the internet" property of the §4-7
fully local stack.

    python3 app.py
"""

from __future__ import annotations

import logging
import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import load_config
from dify_client import DifyClient
from formatting import ACTION_REPLY, ACTION_RESOLVE, VIEW_REPLY
from handlers import Bridge
from store import ConversationStore


def build_app() -> tuple[App, str]:
    config = load_config()
    bridge = Bridge(
        config,
        DifyClient(config.dify_api_base, config.dify_api_key, timeout=config.dify_timeout),
        ConversationStore(config.db_path),
    )
    app = App(token=config.slack_bot_token)

    @app.event("app_mention")
    def on_mention(event, client):
        bridge.handle_question(event, client)

    @app.event("message")
    def on_message(event, client):
        # Channel messages arrive only as app_mention; plain `message` events are
        # handled for direct messages alone.
        if event.get("channel_type") == "im":
            bridge.handle_question(event, client)

    @app.action(ACTION_REPLY)
    def on_reply_button(ack, body, client):
        ack()
        bridge.open_reply_modal(body, client)

    @app.action(ACTION_RESOLVE)
    def on_resolve_button(ack, body, client):
        ack()
        bridge.resolve(body, client)

    @app.view(VIEW_REPLY)
    def on_reply_submit(ack, body, view, client):
        bridge.submit_reply(body, view, client, ack)

    return app, config.slack_app_token


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app, app_token = build_app()
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
