"""Verify Telegram Login ID tokens and extract their subject and nonce."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import jwt
from jwt import PyJWKClient

TELEGRAM_ISSUER = "https://oauth.telegram.org"
TELEGRAM_JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
MAX_ID_TOKEN_LENGTH = 8192
MAX_CLAIM_LENGTH = 128

KeyResolver = Callable[[str], Any]

_INVALID_TOKEN_MESSAGE = "Telegram token is invalid"


class TelegramTokenInvalid(Exception):
    """The Telegram ID token is invalid."""


class TelegramUnavailable(Exception):
    """The Telegram signing keys could not be fetched."""


@dataclass(frozen=True, slots=True)
class TelegramClaims:
    subject: str
    nonce: str


def make_jwks_resolver(url: str = TELEGRAM_JWKS_URL, timeout: float = 5.0) -> KeyResolver:
    client = PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=timeout)

    def resolve(token: str) -> Any:
        return client.get_signing_key_from_jwt(token).key

    return resolve


class TelegramTokenVerifier:
    def __init__(self, client_id: str, key_resolver: KeyResolver, leeway_seconds: int = 30) -> None:
        self._client_id = client_id
        self._key_resolver = key_resolver
        self._leeway_seconds = leeway_seconds

    def verify(self, id_token: str, now: datetime) -> TelegramClaims:
        if len(id_token) > MAX_ID_TOKEN_LENGTH or not id_token.isascii():
            raise TelegramTokenInvalid(_INVALID_TOKEN_MESSAGE)

        try:
            key = self._key_resolver(id_token)
        except jwt.PyJWKClientConnectionError:
            raise TelegramUnavailable("Telegram signing keys are unavailable") from None
        except jwt.PyJWTError:
            raise TelegramTokenInvalid(_INVALID_TOKEN_MESSAGE) from None

        try:
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=TELEGRAM_ISSUER,
                options={
                    "require": ["iss", "aud", "sub", "exp", "iat", "nonce"],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.PyJWTError:
            raise TelegramTokenInvalid(_INVALID_TOKEN_MESSAGE) from None

        exp = claims["exp"]
        iat = claims["iat"]
        if not isinstance(exp, int) or isinstance(exp, bool):
            raise TelegramTokenInvalid(_INVALID_TOKEN_MESSAGE)
        if not isinstance(iat, int) or isinstance(iat, bool):
            raise TelegramTokenInvalid(_INVALID_TOKEN_MESSAGE)

        now_ts = int(now.timestamp())
        if now_ts > exp + self._leeway_seconds or iat > now_ts + self._leeway_seconds:
            raise TelegramTokenInvalid(_INVALID_TOKEN_MESSAGE)

        subject = claims["sub"]
        nonce = claims["nonce"]
        if not isinstance(subject, str) or not 1 <= len(subject) <= MAX_CLAIM_LENGTH:
            raise TelegramTokenInvalid(_INVALID_TOKEN_MESSAGE)
        if not isinstance(nonce, str) or not 1 <= len(nonce) <= MAX_CLAIM_LENGTH:
            raise TelegramTokenInvalid(_INVALID_TOKEN_MESSAGE)

        return TelegramClaims(subject=subject, nonce=nonce)
