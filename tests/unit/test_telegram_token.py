from datetime import UTC, datetime
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from english_for_developers.accounts import telegram
from english_for_developers.accounts.telegram import (
    TELEGRAM_ISSUER,
    TELEGRAM_JWKS_URL,
    TelegramClaims,
    TelegramTokenInvalid,
    TelegramTokenVerifier,
    TelegramUnavailable,
    make_jwks_resolver,
)

CLIENT_ID = "123456789"
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
NOW_TS = int(NOW.timestamp())
SUBJECT = "1234123412341234123"
NONCE = "n-abc"


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def payload() -> dict[str, object]:
    return {
        "iss": TELEGRAM_ISSUER,
        "aud": CLIENT_ID,
        "sub": SUBJECT,
        "iat": NOW_TS - 60,
        "exp": NOW_TS + 3600,
        "nonce": NONCE,
    }


@pytest.fixture
def verifier(private_key: rsa.RSAPrivateKey) -> TelegramTokenVerifier:
    public_key = private_key.public_key()
    return TelegramTokenVerifier(CLIENT_ID, key_resolver=lambda token: public_key)


@pytest.mark.parametrize(
    "extra_claims",
    [
        pytest.param({}, id="base"),
        pytest.param({"id": 42, "name": "Example"}, id="extra-claims"),
        pytest.param({"aud": [CLIENT_ID]}, id="list-audience"),
        pytest.param({"exp": NOW_TS - 30}, id="expiration-at-leeway"),
        pytest.param({"iat": NOW_TS + 30}, id="issued-at-leeway"),
    ],
)
def test_verify_accepts_valid_claims(
    verifier: TelegramTokenVerifier,
    private_key: rsa.RSAPrivateKey,
    payload: dict[str, object],
    extra_claims: dict[str, object],
) -> None:
    token = jwt.encode(payload | extra_claims, private_key, algorithm="RS256")

    assert verifier.verify(token, NOW) == TelegramClaims(subject=SUBJECT, nonce=NONCE)


def test_verify_rejects_wrong_signature_without_exposing_token_or_subject(
    verifier: TelegramTokenVerifier, payload: dict[str, object]
) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(payload, other_key, algorithm="RS256")

    with pytest.raises(TelegramTokenInvalid) as exc_info:
        verifier.verify(token, NOW)

    assert token not in str(exc_info.value)
    assert SUBJECT not in str(exc_info.value)


@pytest.mark.parametrize(
    ("algorithm", "key"), [("HS256", "s" * 32), ("none", None)], ids=["hs256", "unsigned"]
)
def test_verify_rejects_algorithms_other_than_rs256(
    verifier: TelegramTokenVerifier, payload: dict[str, object], algorithm: str, key: str | None
) -> None:
    token = jwt.encode(payload, key, algorithm=algorithm)

    with pytest.raises(TelegramTokenInvalid):
        verifier.verify(token, NOW)


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        pytest.param("iss", "https://evil.example", id="wrong-issuer"),
        pytest.param("aud", "987", id="wrong-audience"),
        pytest.param("aud", ["987"], id="wrong-list-audience"),
        pytest.param("iat", NOW_TS + 31, id="issued-too-far-in-future"),
        pytest.param("exp", "9999999999", id="string-expiration"),
        pytest.param("exp", True, id="boolean-expiration"),
        pytest.param("iat", 1.5, id="float-issued-at"),
        pytest.param("sub", "", id="empty-subject"),
        pytest.param("sub", 42, id="integer-subject"),
        pytest.param("sub", "x" * 129, id="long-subject"),
        pytest.param("nonce", "", id="empty-nonce"),
        pytest.param("nonce", 1, id="integer-nonce"),
        pytest.param("nonce", "n" * 129, id="long-nonce"),
    ],
)
def test_verify_rejects_invalid_claims(
    verifier: TelegramTokenVerifier,
    private_key: rsa.RSAPrivateKey,
    payload: dict[str, object],
    claim: str,
    value: object,
) -> None:
    token = jwt.encode(payload | {claim: value}, private_key, algorithm="RS256")

    with pytest.raises(TelegramTokenInvalid):
        verifier.verify(token, NOW)


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "exp", "iat", "nonce"])
def test_verify_rejects_missing_required_claims(
    verifier: TelegramTokenVerifier,
    private_key: rsa.RSAPrivateKey,
    payload: dict[str, object],
    claim: str,
) -> None:
    del payload[claim]
    token = jwt.encode(payload, private_key, algorithm="RS256")

    with pytest.raises(TelegramTokenInvalid):
        verifier.verify(token, NOW)


def test_verify_rejects_expiration_beyond_leeway_without_exposing_token_or_subject(
    verifier: TelegramTokenVerifier,
    private_key: rsa.RSAPrivateKey,
    payload: dict[str, object],
) -> None:
    token = jwt.encode(payload | {"exp": NOW_TS - 31}, private_key, algorithm="RS256")

    with pytest.raises(TelegramTokenInvalid) as exc_info:
        verifier.verify(token, NOW)

    assert token not in str(exc_info.value)
    assert SUBJECT not in str(exc_info.value)


@pytest.mark.parametrize(
    ("subject", "nonce"),
    [("x" * 128, NONCE), (SUBJECT, "n" * 128)],
    ids=["subject-at-limit", "nonce-at-limit"],
)
def test_verify_accepts_claims_at_maximum_length(
    verifier: TelegramTokenVerifier,
    private_key: rsa.RSAPrivateKey,
    payload: dict[str, object],
    subject: str,
    nonce: str,
) -> None:
    token = jwt.encode(payload | {"sub": subject, "nonce": nonce}, private_key, algorithm="RS256")

    assert verifier.verify(token, NOW) == TelegramClaims(subject=subject, nonce=nonce)


@pytest.mark.parametrize("token", ["x" * 8193, "abcй"], ids=["too-long", "non-ascii"])
def test_verify_rejects_invalid_input_before_resolving_key(token: str) -> None:
    def resolver(raw_token: str) -> rsa.RSAPublicKey:
        raise AssertionError("Key resolver must not be called")

    verifier = TelegramTokenVerifier(CLIENT_ID, key_resolver=resolver)

    with pytest.raises(TelegramTokenInvalid):
        verifier.verify(token, NOW)


def test_verify_rejects_malformed_token(verifier: TelegramTokenVerifier) -> None:
    with pytest.raises(TelegramTokenInvalid):
        verifier.verify("abc", NOW)


@pytest.mark.parametrize(
    ("resolver_error", "expected_error"),
    [
        (jwt.PyJWKClientConnectionError("down"), TelegramUnavailable),
        (jwt.PyJWKClientError("kid not found"), TelegramTokenInvalid),
    ],
    ids=["connection-error", "missing-key"],
)
def test_verify_maps_key_resolver_errors(
    private_key: rsa.RSAPrivateKey,
    payload: dict[str, object],
    resolver_error: jwt.PyJWTError,
    expected_error: type[Exception],
) -> None:
    def resolver(raw_token: str) -> rsa.RSAPublicKey:
        raise resolver_error

    verifier = TelegramTokenVerifier(CLIENT_ID, key_resolver=resolver)
    token = jwt.encode(payload, private_key, algorithm="RS256")

    with pytest.raises(expected_error) as exc_info:
        verifier.verify(token, NOW)

    if expected_error is TelegramUnavailable:
        assert not isinstance(exc_info.value, TelegramTokenInvalid)


@pytest.mark.parametrize(
    ("args", "kwargs", "expected_uri", "expected_timeout"),
    [
        ((), {}, TELEGRAM_JWKS_URL, 5.0),
        (("https://x/jwks",), {"timeout": 1.5}, "https://x/jwks", 1.5),
    ],
    ids=["defaults", "custom-url-and-timeout"],
)
def test_make_jwks_resolver_constructs_and_reuses_one_client(
    monkeypatch: pytest.MonkeyPatch,
    args: tuple[str, ...],
    kwargs: dict[str, float],
    expected_uri: str,
    expected_timeout: float,
) -> None:
    constructions: list[tuple[str, bool, int, float]] = []
    requested_tokens: list[str] = []
    public_key = object()

    class FakePyJWKClient:
        def __init__(self, uri: str, *, cache_keys: bool, lifespan: int, timeout: float) -> None:
            constructions.append((uri, cache_keys, lifespan, timeout))

        def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
            requested_tokens.append(token)
            return SimpleNamespace(key=public_key)

    monkeypatch.setattr(telegram, "PyJWKClient", FakePyJWKClient)

    resolver = make_jwks_resolver(*args, **kwargs)

    expected_constructions = [(expected_uri, True, 3600, expected_timeout)]
    assert constructions == expected_constructions
    assert resolver("tok") is public_key
    assert resolver("tok") is public_key
    assert requested_tokens == ["tok", "tok"]
    assert constructions == expected_constructions
