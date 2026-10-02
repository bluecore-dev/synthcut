import uuid

import jwt
import pytest
from synthcut_api.auth.tokens import TokenError, issue_access_token, verify_access_token
from synthcut_core.settings import Settings


def settings(**kw):
    return Settings(session_secret="x" * 48, **kw)


def test_round_trip():
    s = settings()
    uid = uuid.uuid4()
    token, expires = issue_access_token(uid, 42, s)
    claims = verify_access_token(token, s)
    assert (
        claims.user_id == uid
        and claims.telegram_id == 42
        and claims.expires_at == expires.replace(microsecond=0)
    )


def test_expired_token_rejected():
    s = settings(access_token_ttl_seconds=-10)
    token, _ = issue_access_token(uuid.uuid4(), 42, s)
    with pytest.raises(TokenError):
        verify_access_token(token, s)


def test_token_signed_with_other_secret_rejected():
    token, _ = issue_access_token(uuid.uuid4(), 42, Settings(session_secret="y" * 48))
    with pytest.raises(TokenError):
        verify_access_token(token, settings())


def test_algorithm_none_rejected():
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "tg": 1, "typ": "access", "iss": "synthcut"}, key=None, algorithm="none"
    )
    with pytest.raises(TokenError):
        verify_access_token(forged, settings())


def test_short_secret_refused():
    with pytest.raises(TokenError):
        issue_access_token(uuid.uuid4(), 1, Settings(session_secret="short"))
