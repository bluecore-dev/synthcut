"""Phase 10 memory rules: quick feedback → explained preference changes, and
stored preferences overlaid on the defaults (bad stored values ignored)."""

from types import SimpleNamespace

import pytest
from synthcut_core.preferences import FEEDBACK_RULES, apply_feedback, overlay
from synthcut_schemas.preferences import EditDefaults, FeedbackCode


def test_every_feedback_code_has_a_rule_and_a_label():
    assert set(FEEDBACK_RULES) == set(FeedbackCode.__args__)
    assert all(label for label, _ in FEEDBACK_RULES.values())


def test_denoise_steps_and_explained_changes():
    strong = EditDefaults(denoise="strong")
    after, changes = apply_feedback(strong, ["voice_robotic"])
    assert after.denoise == "medium"
    assert [c.label for c in changes] == ["Shovqin tozalash: kuchli → o'rta"]
    assert apply_feedback(EditDefaults(denoise="auto"), ["voice_robotic"])[0].denoise == "light"
    assert apply_feedback(EditDefaults(denoise="auto"), ["noise_left"])[0].denoise == "medium"
    off, nothing = apply_feedback(EditDefaults(denoise="off"), ["voice_robotic"])
    assert off.denoise == "off" and nothing == []  # already at the limit: no fake change


def test_pauses_colour_loudness_and_captions():
    p = EditDefaults()
    assert apply_feedback(p, ["cut_too_much"])[0].min_pause == pytest.approx(0.9)
    assert apply_feedback(EditDefaults(min_pause=1.9), ["cut_too_much"])[0].min_pause == 2.0
    less, changes = apply_feedback(EditDefaults(remove_pauses=False), ["cut_too_little"])
    assert less.remove_pauses and less.min_pause == pytest.approx(0.45) and len(changes) == 2
    assert apply_feedback(p, ["colour_too_strong"])[0].intensity == pytest.approx(0.6)
    assert apply_feedback(p, ["colour_too_weak"])[0].intensity == 1.0
    assert apply_feedback(EditDefaults(loudness="broadcast"), ["too_quiet"])[0].loudness == "podcast"
    assert apply_feedback(EditDefaults(loudness="youtube"), ["too_loud"])[0].loudness == "podcast"
    assert apply_feedback(p, ["too_quiet"])[1] == []  # social is already the loudest standard
    assert apply_feedback(p, ["no_captions"])[0].captions == "off"
    assert apply_feedback(EditDefaults(captions="off"), ["want_captions"])[0].captions == "dynamic"
    assert apply_feedback(EditDefaults(captions="bold"), ["want_captions"])[0].captions == "bold"


def test_codes_apply_in_order_and_net_changes_are_reported():
    after, changes = apply_feedback(EditDefaults(), ["colour_too_strong", "colour_too_weak"])
    assert after.intensity == pytest.approx(0.8) and changes == []


def test_stored_preferences_overlay_defaults_and_skip_values_a_release_rejects():
    rows = [
        SimpleNamespace(key="denoise", value="light", source="feedback"),
        SimpleNamespace(key="captions", value="karaoke", source="choice"),
        SimpleNamespace(key="intensity", value=7, source="choice"),  # out of range today
    ]
    values, sources = overlay(rows)
    assert (values.denoise, values.captions, values.intensity) == ("light", "karaoke", 0.8)
    assert sources == {"denoise": "feedback", "captions": "choice"}
