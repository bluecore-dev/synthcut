"""Phase 4 end to end: ingestion queues transcription, the worker turns the
speech track into a ``transcript/1`` document, subtitles and a stage update,
and the API serves them (spec §13). The engine is a fake with fixed words —
the real Whisper is exercised in tests/unit and on the server."""

import shutil
import subprocess
import uuid

import httpx
import pytest
from sqlalchemy import select
from synthcut_core.models import AssetTranscript, Event, Job, MediaFile, ProjectStage
from synthcut_speech.engines import EngineResult, FasterWhisperEngine, RawSegment, RawWord
from synthcut_worker.main import Worker
from synthcut_worker.speech import jobs as speech_jobs

from .conftest import SECOND_USER, login, make_project
from .test_ingest import run_worker, upload

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("speech-media")
    ff(
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=6",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(d / "talk.mp4"),
    )  # fmt: skip
    # tone 2 s, silence 2 s, tone 2 s
    ff(
        "-f", "lavfi", "-i", "aevalsrc='if(between(t,2,4),0,0.5*sin(2*PI*300*t))':s=48000:d=6",
        str(d / "gap.wav"),
    )  # fmt: skip
    ff("-f", "lavfi", "-i", "testsrc2=size=800x600:duration=1", "-frames:v", "1", str(d / "still.png"))
    return d


class FakeEngine:
    route = "fake:words"

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, *, language, on_progress=None, check=None):
        self.calls.append({"language": language, "seconds": len(audio) / 16000})
        if on_progress:
            on_progress(0.5)
        if check:
            check()
        return EngineResult(
            language=language or "uz",
            language_probability=None if language else 0.81,
            segments=[
                RawSegment(
                    0.2,
                    1.5,
                    " Salom, bu sinov.",
                    [
                        RawWord(" Salom,", 0.2, 0.6, 0.9),
                        RawWord(" bu", 0.7, 0.9, 0.8),
                        RawWord(" sinov.", 1.0, 1.5, 0.95),
                    ],
                ),
                RawSegment(
                    2.0,
                    3.0,
                    " Savol bormi?",
                    [RawWord(" Savol", 2.0, 2.4, 0.9), RawWord(" bormi?", 2.5, 3.0, 0.9)],
                ),
            ],
            seconds=0.1,
        )


@pytest.fixture
def fake_engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(speech_jobs, "engine_for", lambda *a, **k: engine)
    return engine


@pytest.fixture
def speech_settings(settings):
    return settings.model_copy(update={"speech_auto": True})


async def test_ingestion_queues_transcription_and_the_api_serves_it(
    client, auth, speech_settings, media, Session, fake_engine
):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    assert run_worker(speech_settings) == ["ingest.asset", "speech.transcribe"]
    assert fake_engine.calls[0]["language"] is None  # project language "auto" → detect
    assert abs(fake_engine.calls[0]["seconds"] - 6.0) < 0.1

    detail = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()
    assert (detail["transcript_status"], detail["transcript_language"]) == ("done", "uz")
    summary = detail["transcript"]
    assert summary["engine"] == "fake:words" and summary["word_count"] == 5
    assert summary["requested_language"] == "auto" and summary["language_probability"] == 0.81
    files = {f["kind"] for f in detail["files"]}
    assert {"subtitles_vtt", "subtitles_srt"} <= files and "transcript" not in files
    async with httpx.AsyncClient() as s3:
        vtt = await s3.get(summary["subtitles_vtt"]["url"])
        assert vtt.status_code == 200 and vtt.text.startswith("WEBVTT")
        assert "00:00:00.200 --> 00:00:01.500\nSalom, bu sinov." in vtt.text
        srt = await s3.get(summary["subtitles_srt"]["url"])
        assert srt.text.startswith("1\n00:00:00,200 --> 00:00:01,500\n")

    transcript = (await client.get(f"/api/v1/assets/{asset['id']}/transcript", headers=auth)).json()
    assert transcript["schema_version"] == "transcript/1" and transcript["language_forced"] is False
    assert [s["text"] for s in transcript["segments"]] == ["Salom, bu sinov.", "Savol bormi?"]
    assert [s["question"] for s in transcript["segments"]] == [False, True]
    assert [w["word"] for w in transcript["segments"][0]["words"]] == ["Salom,", "bu", "sinov."]
    assert transcript["silences"] == []  # a continuous tone
    assert [(c["word_start"], c["word_end"]) for c in transcript["cues"]] == [(0, 3), (3, 5)]

    listed = (await client.get(f"/api/v1/projects/{project['id']}/assets", headers=auth)).json()["items"]
    assert listed[0]["transcript_status"] == "done"

    pid = uuid.UUID(project["id"])
    with Session() as s:
        stage = s.get(ProjectStage, (pid, "transcription"))
        assert stage.status == "done" and stage.detail == "1 ta faylda nutq · 5 so'z"
        assert "transcript.ready" in set(s.scalars(select(Event.type).where(Event.project_id == pid)))
        notify = s.scalars(
            select(Job.idempotency_key).where(Job.kind == "notify.telegram", Job.project_id == pid)
        )
        assert any(k.startswith("notify.transcripts_done:") for k in notify)
        kinds = set(s.scalars(select(MediaFile.kind).where(MediaFile.asset_id == uuid.UUID(asset["id"]))))
        assert {"transcript", "subtitles_vtt", "subtitles_srt", "audio_speech"} <= kinds


async def test_retranscribe_with_a_forced_language(
    client, auth, speech_settings, media, Session, fake_engine
):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    run_worker(speech_settings)
    url = f"/api/v1/assets/{asset['id']}/transcribe"

    r = await client.post(url, json={"language": "ru"}, headers=auth)
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["requested_language"] == "ru"
    again = await client.post(url, json={"language": "ru"}, headers=auth)
    assert again.status_code == 202  # a double tap queues once
    other = await client.post(url, json={"language": "en"}, headers=auth)
    assert other.status_code == 409 and other.json()["error"]["code"] == "transcription_running"

    assert run_worker(speech_settings) == ["speech.transcribe"]
    assert fake_engine.calls[-1]["language"] == "ru"
    transcript = (await client.get(f"/api/v1/assets/{asset['id']}/transcript", headers=auth)).json()
    assert transcript["language"] == "ru" and transcript["language_forced"] is True
    with Session() as s:
        row = s.scalar(select(AssetTranscript).where(AssetTranscript.asset_id == uuid.UUID(asset["id"])))
        assert (row.status, row.runs) == ("done", 2)
        keys = list(s.scalars(select(Job.idempotency_key).where(Job.kind == "speech.transcribe")))
        assert f"speech.transcribe:{asset['id']}:r2" in keys


async def test_audio_file_gets_silences_and_images_skip_the_stage(
    client, auth, speech_settings, media, Session, fake_engine
):
    project = await make_project(client, auth)
    audio = await upload(client, auth, project["id"], media / "gap.wav", "audio/wav")
    run_worker(speech_settings)
    transcript = (await client.get(f"/api/v1/assets/{audio['id']}/transcript", headers=auth)).json()
    [silence] = transcript["silences"]
    assert abs(silence["start"] - 2.0) < 0.1 and abs(silence["end"] - 4.0) < 0.1

    stills = await make_project(client, auth, name="Rasmlar")
    image = await upload(client, auth, stills["id"], media / "still.png", "image/png")
    assert run_worker(speech_settings) == ["ingest.asset"]
    with Session() as s:
        stage = s.get(ProjectStage, (uuid.UUID(stills["id"]), "transcription"))
        assert (stage.status, stage.detail) == ("skipped", "Ovozli fayl yo'q")
    r = await client.post(f"/api/v1/assets/{image['id']}/transcribe", json={}, headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_speech_track"
    assert (await client.get(f"/api/v1/assets/{image['id']}/transcript", headers=auth)).status_code == 404


async def test_transcript_is_owner_scoped(client, auth, speech_settings, media, fake_engine):
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    run_worker(speech_settings)
    assert (await client.get(f"/api/v1/assets/{asset['id']}/transcript", headers=auth)).status_code == 200
    other = await login(client, SECOND_USER)
    assert (await client.get(f"/api/v1/assets/{asset['id']}/transcript", headers=other)).status_code == 404
    r = await client.post(f"/api/v1/assets/{asset['id']}/transcribe", json={}, headers=other)
    assert r.status_code == 404


async def test_missing_model_fails_with_a_reason(
    client, auth, speech_settings, media, Session, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        speech_jobs,
        "engine_for",
        lambda *a, **k: FasterWhisperEngine("tiny", models_dir=tmp_path, threads=1),
    )
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    run_worker(speech_settings)
    detail = (await client.get(f"/api/v1/assets/{asset['id']}", headers=auth)).json()
    assert detail["transcript"]["status"] == "failed"
    assert detail["transcript"]["error"].startswith("Nutq dvigateli tayyor emas")
    with Session() as s:
        job = s.scalar(
            select(Job).where(Job.kind == "speech.transcribe", Job.project_id == uuid.UUID(project["id"]))
        )
        assert job.status == "dead" and job.attempts == 1  # permanent: no pointless retry
        stage = s.get(ProjectStage, (uuid.UUID(project["id"]), "transcription"))
        assert stage.status == "failed"


async def test_interrupted_transcription_goes_back_to_the_queue(
    client, auth, speech_settings, media, Session, monkeypatch
):
    from synthcut_worker.context import JobInterrupted

    class Interrupted(FakeEngine):
        def transcribe(self, audio, **kw):
            raise JobInterrupted("shutdown")

    monkeypatch.setattr(speech_jobs, "engine_for", lambda *a, **k: Interrupted())
    project = await make_project(client, auth)
    asset = await upload(client, auth, project["id"], media / "talk.mp4", "video/mp4")
    # One pass by hand: run_worker would claim the handed-back job again forever.
    worker = Worker(speech_settings.model_copy(update={"worker_queues": "cpu"}), worker_id="test-interrupt")
    worker._run(worker._claim())
    job = worker._claim()
    assert job.kind == "speech.transcribe"
    worker._run(job)
    with Session() as s:
        row = s.scalar(select(AssetTranscript).where(AssetTranscript.asset_id == uuid.UUID(asset["id"])))
        job = s.scalar(
            select(Job).where(Job.kind == "speech.transcribe", Job.project_id == uuid.UUID(project["id"]))
        )
        assert row.status == "queued" and job.status == "queued"  # handed back, not failed
        stage = s.get(ProjectStage, (uuid.UUID(project["id"]), "transcription"))
        assert stage.status == "queued"
