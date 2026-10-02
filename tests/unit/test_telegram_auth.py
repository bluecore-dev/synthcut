import json
import time
from urllib.parse import parse_qsl, urlencode

import pytest
from synthcut_api.auth.telegram import InitDataError, sign_init_data, validate_init_data

TOKEN = "123456:TEST-token-for-unit-tests"


def fields(**overrides):
    base = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(
            {"id": 7914882474, "first_name": "Omonjon", "username": "omonjon", "language_code": "uz"}
        ),
    }
    base.update(overrides)
    return base


def test_valid_init_data_is_accepted():
    data = validate_init_data(sign_init_data(fields(), TOKEN), TOKEN, max_age_seconds=3600)
    assert data.user.id == 7914882474
    assert data.user.username == "omonjon"
    assert data.query_id == "AAHdF6IQAAAAAN0XohDhrOrc"


def test_signature_field_inside_hmac_is_accepted():
    # Telegram (Bot API 8.0+) sends an Ed25519 `signature` field as well.
    raw = sign_init_data(fields(signature="c2lnbmF0dXJl"), TOKEN)
    assert validate_init_data(raw, TOKEN, max_age_seconds=3600).user.id == 7914882474


def test_signature_field_outside_hmac_is_accepted():
    f = fields()
    signed = dict(parse_qsl(sign_init_data(f, TOKEN)))
    signed["signature"] = "c2lnbmF0dXJl"
    assert validate_init_data(urlencode(signed), TOKEN, max_age_seconds=3600).user.id == 7914882474


def test_tampered_user_is_rejected():
    signed = dict(parse_qsl(sign_init_data(fields(), TOKEN)))
    signed["user"] = json.dumps({"id": 1, "first_name": "Mallory"})
    with pytest.raises(InitDataError) as exc:
        validate_init_data(urlencode(signed), TOKEN, max_age_seconds=3600)
    assert exc.value.code == "bad_hash"


def test_other_bots_token_is_rejected():
    with pytest.raises(InitDataError) as exc:
        validate_init_data(sign_init_data(fields(), "999:other-bot"), TOKEN, max_age_seconds=3600)
    assert exc.value.code == "bad_hash"


def test_missing_hash_is_rejected():
    with pytest.raises(InitDataError) as exc:
        validate_init_data(urlencode(fields()), TOKEN, max_age_seconds=3600)
    assert exc.value.code == "missing_hash"


def test_expired_init_data_is_rejected():
    raw = sign_init_data(fields(auth_date=str(int(time.time()) - 7200)), TOKEN)
    with pytest.raises(InitDataError) as exc:
        validate_init_data(raw, TOKEN, max_age_seconds=3600)
    assert exc.value.code == "expired"


def test_future_init_data_is_rejected():
    raw = sign_init_data(fields(auth_date=str(int(time.time()) + 3600)), TOKEN)
    with pytest.raises(InitDataError) as exc:
        validate_init_data(raw, TOKEN, max_age_seconds=3600)
    assert exc.value.code == "expired"


def test_duplicate_keys_are_rejected():
    raw = sign_init_data(fields(), TOKEN) + "&auth_date=1"
    with pytest.raises(InitDataError) as exc:
        validate_init_data(raw, TOKEN, max_age_seconds=3600)
    assert exc.value.code == "malformed"


def test_unconfigured_token_fails_closed():
    with pytest.raises(InitDataError) as exc:
        validate_init_data(sign_init_data(fields(), TOKEN), "", max_age_seconds=3600)
    assert exc.value.code == "not_configured"
