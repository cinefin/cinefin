"""API keys: bearer tokens for the Cinefin API. Only a SHA-256 hash is stored;
the plaintext is shown once at creation and is unrecoverable afterwards."""

import hashlib
import secrets

from django.db import models
from django.utils import timezone

KEY_PREFIX = "cplx"
_SECRET_BYTES = 24


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str]:
    secret = secrets.token_hex(_SECRET_BYTES)
    raw_key = f"{KEY_PREFIX}_{secret}"
    display_prefix = raw_key[: len(KEY_PREFIX) + 1 + 8]
    return raw_key, display_prefix


class APIKey(models.Model):
    name = models.CharField(max_length=100, help_text="Human label, e.g. 'Home Assistant'")
    prefix = models.CharField(max_length=32, help_text="Display prefix, e.g. cplx_a1b2c3d4")
    key_hash = models.CharField(max_length=64, unique=True, db_index=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @classmethod
    def create(cls, name: str) -> tuple["APIKey", str]:
        raw_key, prefix = generate_key()
        instance = cls.objects.create(name=name.strip() or "API key", prefix=prefix, key_hash=hash_key(raw_key))
        return instance, raw_key

    @classmethod
    def resolve(cls, raw_key: str) -> "APIKey | None":
        if not raw_key:
            return None
        try:
            key = cls.objects.get(key_hash=hash_key(raw_key))
        except cls.DoesNotExist:
            return None
        now = timezone.now()
        # Records last_used_at at most once a minute so auth stays one indexed read.
        if key.last_used_at is None or (now - key.last_used_at).total_seconds() > 60:
            key.last_used_at = now
            key.save(update_fields=["last_used_at"])
        return key
