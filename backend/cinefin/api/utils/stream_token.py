"""Signed tokens for the /stream/ media endpoints.

MPV fetches playlist items over plain HTTP with no session, so the stream URLs
must carry their own auth: an HMAC over kind+id keyed by SECRET_KEY. Tokens are
stateless and never expire; rotating SECRET_KEY invalidates them all.
"""

import hashlib
import hmac

from django.conf import settings


def make_stream_token(kind: str, obj_id: int) -> str:
    msg = f"stream:{kind}:{obj_id}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:32]


def check_stream_token(kind: str, obj_id: int, token: str | None) -> bool:
    if not token:
        return False
    return hmac.compare_digest(make_stream_token(kind, obj_id), str(token))
