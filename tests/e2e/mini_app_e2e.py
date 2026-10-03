"""End-to-end check of a *deployed* Mini App in real browser engines.

Simulates a Telegram launch exactly the way Telegram does it: the page is
opened with a freshly signed initData in the URL hash (#tgWebAppData=…), which
telegram-web-app.js reads. Then it creates a project, uploads a file through
the real nginx → Garage path, interrupts a second upload with a page reload,
resumes it by picking the same file again, and checks the pipeline.

Not collected by pytest (needs a live deployment and the bot token):

    SYNTHCUT_E2E_URL=https://synthcut.socialmarketing.uz \\
    SYNTHCUT_E2E_BOT_TOKEN=... SYNTHCUT_E2E_TELEGRAM_ID=... \\
    uv run --with playwright python tests/e2e/mini_app_e2e.py [chromium webkit]

It prints the ids of the projects it created; remove them afterwards.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

URL = os.environ["SYNTHCUT_E2E_URL"].rstrip("/")
TOKEN = os.environ["SYNTHCUT_E2E_BOT_TOKEN"]
TG_ID = int(os.environ["SYNTHCUT_E2E_TELEGRAM_ID"])
SHOTS = Path(os.environ.get("SYNTHCUT_E2E_SHOTS", tempfile.gettempdir())) / "synthcut-e2e"
MIB = 1024 * 1024


def signed_init_data() -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAE2E0000000000000000000",
        "user": json.dumps({"id": TG_ID, "first_name": "E2E", "language_code": "uz"}, separators=(",", ":")),
    }
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


def launch_url() -> str:
    params = {
        "tgWebAppData": signed_init_data(),
        "tgWebAppVersion": "8.0",
        "tgWebAppPlatform": "ios",
        "tgWebAppThemeParams": json.dumps({"bg_color": "#0b0c0f", "text_color": "#ffffff"}),
    }
    return f"{URL}/#{urllib.parse.urlencode(params)}"


def make_file(directory: Path, name: str, size: int) -> Path:
    path = directory / name
    with path.open("wb") as fh:
        fh.write(os.urandom(size))
    return path


def make_video(directory: Path, name: str) -> Path:
    """~40 MB real 1080p clip with a scene cut and audio, so ingestion has work."""
    path = directory / name
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=4",
         "-f", "lavfi", "-i", "smptebars=size=1920x1080:rate=30:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=8",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
         "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "40M", "-minrate", "40M", "-maxrate", "40M",
         "-bufsize", "20M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )  # fmt: skip
    return path


def shot(page: Page, engine: str, step: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{engine}-{step}.png"), full_page=True)


def run(engine: str, browser_type, workdir: Path) -> str:
    browser = browser_type.launch()
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True
    )
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(str(e)))

    page.goto(launch_url())
    expect(page.get_by_role("button", name="Yangi loyiha")).to_be_visible(timeout=30_000)
    shot(page, engine, "1-home")

    page.get_by_role("button", name="Yangi loyiha").click()
    page.get_by_placeholder("Masalan").fill(f"E2E {engine} {time.strftime('%H:%M:%S')}")
    expect(page.get_by_text("Reels / TikTok / Shorts")).to_be_visible()
    shot(page, engine, "2-new-project")
    page.get_by_role("button", name="Loyihani yaratish").click()
    expect(page).to_have_url(re.compile(r"/p/[0-9a-f-]{36}\?tab=assets"), timeout=15_000)
    project_id = re.search(r"/p/([0-9a-f-]{36})", page.url).group(1)

    # 1) A real ~40 MB clip: 3 MD5-signed parts through nginx to Garage, then the
    #    worker ingests it (proxy, thumbnails, shots) and the asset page shows it.
    small = make_video(workdir, f"E2E_{engine}_A001.mp4")
    page.locator("input[type=file]").set_input_files(str(small))
    expect(page.get_by_text("tayyor", exact=True)).to_have_count(1, timeout=300_000)
    shot(page, engine, "3-ingested")
    page.get_by_text(f"E2E_{engine}_A001.mp4").click()
    expect(page.get_by_text("Kadr kesimlari (shots)")).to_be_visible(timeout=15_000)
    expect(page.locator("video")).to_have_count(1)
    shot(page, engine, "3b-asset")
    page.go_back()

    # 2) Interrupt a 50 MiB upload after its first verified part, reload, resume.
    big = make_file(workdir, f"E2E_{engine}_B002.mov", 50 * MIB)
    page.locator("input[type=file]").set_input_files(str(big))
    expect(page.get_by_text(re.compile(r"^[1-3]/4 qism tasdiqlandi"))).to_be_visible(timeout=300_000)
    page.reload()
    expect(page.get_by_text(re.compile("To'xtatilgan"))).to_be_visible(timeout=30_000)
    shot(page, engine, "4-interrupted")
    page.locator("input[type=file]").set_input_files(str(big))
    # Random bytes are not a video: ingestion must fail cleanly, not hang.
    expect(page.get_by_text("xato", exact=True)).to_have_count(1, timeout=300_000)
    shot(page, engine, "5-resumed")

    # 3) The pipeline reflects it.
    page.get_by_role("button", name="Overview").click()
    expect(page.get_by_text("Media Ingest", exact=True)).to_be_visible()
    expect(page.get_by_text("1 ta fayl tayyor, 1 ta o'qilmadi", exact=True)).to_be_visible(timeout=15_000)
    shot(page, engine, "6-overview")
    page.get_by_role("button", name="Logs").click()
    expect(page.get_by_text(re.compile("yuklash davom ettirilmoqda")).first).to_be_visible(timeout=15_000)
    shot(page, engine, "7-logs")

    browser.close()
    # The deliberate reload aborts in-flight progress/SSE requests; WebKit logs
    # an aborted fetch as an "access control checks" failure.
    benign = ("favicon", "due to access control checks")
    fatal = [e for e in console_errors if not any(b in e for b in benign)]
    if fatal:
        raise AssertionError(f"{engine}: console errors: {fatal[:5]}")
    return project_id


def main(engines: list[str]) -> int:
    created = []
    with sync_playwright() as pw, tempfile.TemporaryDirectory() as tmp:
        for engine in engines:
            started = time.monotonic()
            project_id = run(engine, getattr(pw, engine), Path(tmp))
            created.append(project_id)
            print(f"{engine}: OK in {time.monotonic() - started:.0f}s — project {project_id}")
    print("created projects:", " ".join(created))
    print("screenshots:", SHOTS)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["chromium", "webkit"]))
