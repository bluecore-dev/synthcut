import time
import uuid

import pytest
from synthcut_api.uploads.media_types import UnsupportedMediaError, classify, safe_display_name
from synthcut_bot.keyboards.web_app import open_app_keyboard
from synthcut_core.ids import new_id
from synthcut_core.settings import Settings
from synthcut_core.stages import active_stage, overall_progress
from synthcut_schemas.enums import AssetKind, Stage


def test_uuid7_is_versioned_and_time_ordered():
    first = new_id()
    time.sleep(0.002)
    second = new_id()
    assert first.version == 7 and first.variant == uuid.RFC_4122
    assert first < second
    assert len({new_id() for _ in range(5000)}) == 5000


def test_allowlist_parsing_fails_closed():
    assert Settings(authorized_telegram_user_ids="").allowed_telegram_ids == frozenset()
    assert Settings(authorized_telegram_user_ids=" 1, 2;3 ").allowed_telegram_ids == {1, 2, 3}


@pytest.mark.parametrize(
    ("name", "ctype", "kind"),
    [
        ("A001.MOV", "video/quicktime", AssetKind.VIDEO),
        ("voice.wav", "", AssetKind.AUDIO),
        ("logo.png", "image/png", AssetKind.IMAGE),
        ("clip", "video/mp4", AssetKind.VIDEO),
        ("x.braw", "application/octet-stream", AssetKind.VIDEO),
    ],
)
def test_media_classification(name, ctype, kind):
    assert classify(name, ctype)[0] is kind


def test_unsupported_media_rejected():
    with pytest.raises(UnsupportedMediaError):
        classify("setup.exe", "application/x-msdownload")


def test_display_name_drops_directories_and_control_chars():
    assert safe_display_name("C:\\Users\\x\\clip\x00.mov") == "clip.mov"
    assert safe_display_name("../../etc/passwd") == "passwd"


def test_progress_and_active_stage():
    stages = {Stage.UPLOAD.value: ("done", 1.0), Stage.INGEST.value: ("queued", None)}
    assert active_stage(stages) is Stage.INGEST
    assert 0 < overall_progress(stages) < 0.1


def test_web_app_buttons_only_on_https():
    assert open_app_keyboard("http://localhost:3400/") is None
    kb = open_app_keyboard("https://synthcut.example/", uuid.UUID(int=1))
    assert kb.inline_keyboard[0][0].web_app.url == f"https://synthcut.example/?p={uuid.UUID(int=1)}"


def test_fps_choices_match_the_timeline():
    from typing import get_args

    from synthcut_schemas.api import FpsChoice
    from synthcut_schemas.enums import ALLOWED_FPS

    assert set(get_args(FpsChoice)) == set(ALLOWED_FPS)
