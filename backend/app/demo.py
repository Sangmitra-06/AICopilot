"""Sharing the app with a tester through a tunnel: an access gate and a daily spend guard. Both read the environment on
every request, so nothing is cached and the tests can set them per test.

- DEMO_PASSWORD: when set (non-empty), every request needs it once, as HTTP basic auth (any user name). The browser asks
  for it on the first page load and resends it for the API, the PDF and the assets. The password is never logged, never
  echoed and never put in a response.
- MAX_CHAT_CALLS_PER_DAY (default 500): how many chat calls (POST /chat/{pid}, and an opening that really opens) the
  backend answers per UTC day. Counted in the event log under the key "usage:<date>", so a restart does not reset it.
  Once reached, the chat answers with LIMIT_MESSAGE and makes no model call.
"""
import base64
import binascii
import datetime
import hmac
import logging
import os
import threading

from . import store

log = logging.getLogger("copilot.demo")

DEFAULT_MAX = 500
LIMIT_MESSAGE = ("This demo has reached its limit of chat messages for today, so I can't answer right now. "
                 "Your notes and draft are saved; please come back tomorrow.")
REALM = "Reviewer Co-pilot demo"
_LOCK = threading.Lock()


# ------------------------------------------------------------------ access gate

def password(env=None):
    return (os.environ if env is None else env).get("DEMO_PASSWORD") or ""


def authorized(header, secret):
    """Does an Authorization header carry `secret` as basic-auth password (any user name)? Constant-time compare."""
    if not secret:
        return True
    if not header or not header[:6].lower() == "basic ":
        return False
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    _, sep, given = decoded.partition(":")
    return bool(sep) and hmac.compare_digest(given.encode("utf-8"), secret.encode("utf-8"))


class Gate:
    """Pure ASGI middleware: with DEMO_PASSWORD set, a request without it gets a 401 asking for basic auth."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        secret = password()
        if scope["type"] != "http" or not secret:
            return await self.app(scope, receive, send)
        header = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"authorization"), "")
        if authorized(header, secret):
            return await self.app(scope, receive, send)
        body = b"Password required."
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"www-authenticate", f'Basic realm="{REALM}", charset="UTF-8"'.encode()),
                                (b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


# ------------------------------------------------------------------ spend guard

def limit(env=None):
    raw = (os.environ if env is None else env).get("MAX_CHAT_CALLS_PER_DAY", "")
    if not raw.strip():
        return DEFAULT_MAX
    try:
        return int(raw)
    except ValueError:
        log.warning("MAX_CHAT_CALLS_PER_DAY=%r is not a number; using %d", raw, DEFAULT_MAX)
        return DEFAULT_MAX


def usage_key(day=None):
    return "usage:" + (day or datetime.datetime.now(datetime.timezone.utc).date().isoformat())


def used(day=None):
    return sum(1 for e in store.events(usage_key(day)) if e["type"] == "chat_call")


def take(kind):
    """Count one chat call if today's limit allows it. Returns False (and counts nothing) once the limit is reached."""
    with _LOCK:
        if used() >= limit():
            log.warning("daily chat limit reached (%d)", limit())
            return False
        store.log(usage_key(), "chat_call", {"kind": kind})
        return True


def reached():
    return used() >= limit()
