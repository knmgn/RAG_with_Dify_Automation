"""Minimal client for the Dify Self-Hosted **console** API.

The console API is what the Dify web UI itself talks to. Using it lets us
provision the Knowledge base and the Chatflow from code instead of clicking
through the admin screens, so the whole demo environment is reproducible.

Deliberately standard-library only: `git clone` then `python3 scripts/...`
should work with no pip install step.

Two things about this API are easy to get wrong, so they are handled here once:

1. `POST /console/api/login` expects the password **base64 encoded**
   (the backend runs it through `FieldEncryption.decrypt_field`, which is a
   plain base64 decode). Sending the plaintext password gets you a 401.
2. Auth is cookie based, and every non-exempt request additionally needs the
   `X-CSRF-Token` header to echo the `csrf_token` cookie. A bearer token alone
   is not enough — `check_csrf_token()` rejects the request.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / "scripts" / ".dify_admin.env"


class DifyError(RuntimeError):
    """An error response from the console API, with the body kept for context."""

    def __init__(self, status: int, body: str, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}\n{body}")
        self.status = status
        self.body = body
        self.url = url


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Read scripts/.dify_admin.env. Real environment variables win."""
    values: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    for key in list(values) + [
        "DIFY_BASE_URL",
        "DIFY_EMAIL",
        "DIFY_PASSWORD",
        "N8N_WEBHOOK_TOKEN",
        "N8N_INTENT_DISPATCHER_PATH",
    ]:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


class DifyConsole:
    """Authenticated session against `<base_url>/console/api`."""

    def __init__(self, base_url: str, email: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self._password = password
        self._jar = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )

    # ── auth ────────────────────────────────────────────────────────────

    def login(self) -> None:
        if not self._password:
            raise DifyError(0, "DIFY_PASSWORD is empty. Fill it in scripts/.dify_admin.env.", "login")
        encoded = base64.b64encode(self._password.encode("utf-8")).decode("ascii")
        self._request(
            "POST",
            "/login",
            body=json.dumps(
                {"email": self.email, "password": encoded, "language": "ja-JP", "remember_me": True}
            ).encode("utf-8"),
            content_type="application/json",
            with_csrf=False,
        )
        if not self._csrf_token():
            raise DifyError(0, "Login succeeded but no csrf_token cookie was set.", "login")

    def _csrf_token(self) -> str | None:
        for cookie in self._jar:
            if cookie.name in ("csrf_token", "__Host-csrf_token"):
                return cookie.value
        return None

    # ── plumbing ────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        with_csrf: bool = True,
    ) -> Any:
        url = f"{self.base_url}/console/api{path}"
        request = urllib.request.Request(url, data=body, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        if with_csrf:
            token = self._csrf_token()
            if token:
                request.add_header("X-CSRF-Token", token)
        request.add_header("Accept", "application/json")
        try:
            with self._opener.open(request, timeout=120) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise DifyError(exc.code, exc.read().decode("utf-8", "replace"), url) from exc
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request(
            "POST",
            path,
            body=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

    def patch(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request(
            "PATCH",
            path,
            body=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

    def delete(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        if payload is None:
            return self._request("DELETE", path)
        return self._request(
            "DELETE",
            path,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

    def upload_file(self, file_path: Path, source: str = "datasets") -> dict[str, Any]:
        """POST /files/upload as multipart/form-data, hand-rolled."""
        boundary = f"----dify{uuid.uuid4().hex}"
        mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        parts: list[bytes] = []
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="source"\r\n\r\n{source}\r\n'.encode()
        )
        filename = urllib.parse.quote(file_path.name)
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f"filename*=UTF-8''{filename}\r\nContent-Type: {mime}\r\n\r\n".encode()
        )
        parts.append(file_path.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        return self._request(
            "POST",
            "/files/upload",
            body=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
        )


def connect(env: dict[str, str] | None = None) -> DifyConsole:
    """Load credentials, log in, and hand back a ready session."""
    env = env or load_env()
    console = DifyConsole(
        base_url=env.get("DIFY_BASE_URL", "http://localhost"),
        email=env.get("DIFY_EMAIL", ""),
        password=env.get("DIFY_PASSWORD", ""),
    )
    console.login()
    return console
