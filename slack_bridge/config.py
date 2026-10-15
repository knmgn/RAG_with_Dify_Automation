"""Runtime configuration for the Slack bridge, read from environment variables.

Everything secret (Slack tokens, the Dify app key) comes from the environment so
nothing sensitive is ever committed. See .env.example for the full list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """A required setting is missing or malformed."""


@dataclass(frozen=True)
class Config:
    slack_bot_token: str
    slack_app_token: str
    dify_api_key: str
    dify_api_base: str
    # Channel that receives questions the policy does not cover. Leave empty to
    # disable human escalation; the bot still refuses, it just doesn't forward.
    escalation_channel: str
    # The fixed refusal in the system prompt contains this phrase. Detecting it is
    # how the bridge knows the guardrail fired; test_e2e.py relies on the same marker.
    fallback_marker: str
    ui_language: str
    db_path: str
    dify_timeout: float


def _require(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} is not set (see slack_bridge/.env.example)")
    return value


def load_config(env: dict[str, str] | None = None) -> Config:
    env = dict(os.environ if env is None else env)

    bot_token = _require(env, "SLACK_BOT_TOKEN")
    app_token = _require(env, "SLACK_APP_TOKEN")
    if not bot_token.startswith("xoxb-"):
        raise ConfigError("SLACK_BOT_TOKEN must be a bot token (xoxb-...)")
    if not app_token.startswith("xapp-"):
        raise ConfigError("SLACK_APP_TOKEN must be an app-level token (xapp-...) with connections:write")

    language = env.get("UI_LANGUAGE", "ja").strip() or "ja"
    if language not in ("ja", "en"):
        raise ConfigError("UI_LANGUAGE must be 'ja' or 'en'")

    return Config(
        slack_bot_token=bot_token,
        slack_app_token=app_token,
        dify_api_key=_require(env, "DIFY_API_KEY"),
        dify_api_base=env.get("DIFY_API_BASE", "http://api:5001/v1").rstrip("/"),
        escalation_channel=env.get("SLACK_ESCALATION_CHANNEL", "").strip(),
        fallback_marker=env.get("FALLBACK_MARKER", "見当たりませんでした"),
        ui_language=language,
        db_path=env.get("BRIDGE_DB_PATH", "/data/conversations.db"),
        dify_timeout=float(env.get("DIFY_TIMEOUT_SECONDS", "120")),
    )
