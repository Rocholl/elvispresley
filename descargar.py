#!/usr/bin/env python3
"""Descarga grabaciones de un perfil de Smule (canal completo)."""

import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

from playwright.sync_api import sync_playwright

USER = "ElvaTorales1"
ACCOUNT_ID = 2448626046
OUT = Path(__file__).resolve().parent / "canciones"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
API_LIMIT = 25
LOAD_TIMEOUT_S = 90


def curl_json(url: str) -> dict:
    out = subprocess.check_output(
        ["curl", "-sL", url, "-H", f"User-Agent: {UA}", "-H", "Accept: application/json"],
        text=True,
    )
    return json.loads(out)


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return (text or "cancion")[:max_len].strip("-")


def fetch_channel_songs(page, account_id: int, username: str) -> list[dict]:
    catalog = OUT / "catalogo-completo.json"
    if catalog.exists():
        songs = json.loads(catalog.read_text())
        if songs:
            print(f"Catálogo en caché: {len(songs)} canciones", flush=True)
            return songs

    page.goto(f"https://www.smule.com/{username}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    songs, offset = [], 0
    while True:
        data = page.evaluate(
            """async ([accountId, offset, limit]) => {
              const u = `https://www.smule.com/api/profile/performances?accountId=${accountId}&appUid=sing&offset=${offset}&limit=${limit}`;
              const r = await fetch(u, {headers: {Accept: 'application/json'}});
              return r.json();
            }""",
            [account_id, offset, API_LIMIT],
        )
        batch = data.get("list") or []
        if not batch:
            break
        songs.extend(batch)
        offset += len(batch)
        if offset % 500 < API_LIMIT:
            print(f"  listando... {len(songs)}", flush=True)
        if len(batch) < API_LIMIT:
            break
        time.sleep(0.12)

    catalog.write_text(json.dumps(songs, ensure_ascii=False, indent=2))
    return songs


MEDIA_RE = re.compile(r"https://c-cf\.cdn\.smule\.com/.+?\.(?:m4a|mp4)")


def dismiss_cookies(page) -> None:
    for sel in ('button:has-text("Accept Cookies")', 'button:has-text("Aceptar")'):
        btn = page.locator(sel)
        if btn.count():
            try:
                btn.first.click(timeout=2000)
            except Exception:
                pass
            break


def try_play(page) -> None:
    for sel in (
        'button[aria-label*="Play"]',
        ".vjs-big-play-button",
        "button.vjs-play-control",
    ):
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.click(timeout=2000)
                return
            except Exception:
                pass


def media_from_page(page, recording_url: str, timeout_s: int = LOAD_TIMEOUT_S) -> str | None:
    captured: list[str] = []

    def on_response(response):
        if MEDIA_RE.search(response.url):
            captured.append(response.url)

    page.on("response", on_response)
    page.goto(recording_url, wait_until="domcontentloaded", timeout=60000)
    dismiss_cookies(page)

    deadline = time.time() + timeout_s
    play_attempts = 0
    while time.time() < deadline:
        video = page.evaluate(
            "() => document.querySelector('video')?.currentSrc"
            " || document.querySelector('video')?.src || ''"
        )
        if video and MEDIA_RE.search(video):
            return video

        for url in captured:
            if MEDIA_RE.search(url):
                return url

        m = MEDIA_RE.search(page.content())
        if m:
            return m.group(0)

        store_mu = page.evaluate(
            "() => window.DataStore?.Pages?.Recording?.performance?.media_url || null"
        )
        elapsed = timeout_s - (deadline - time.time())
        if elapsed > 30 and not store_mu and not captured and not video:
            return None

        if play_attempts < 4 and elapsed > 4 * (play_attempts + 1):
            try_play(page)
            play_attempts += 1

        page.wait_for_timeout(1000)

    return None


def download_media(url: str, dest: Path) -> None:
    subprocess.run(
        [
            "curl", "-sL", "--retry", "3", "--retry-delay", "2",
            url, "-H", f"User-Agent: {UA}",
            "-H", "Referer: https://www.smule.com/",
            "-H", "Origin: https://www.smule.com",
            "-o", str(dest),
        ],
        check=True,
    )
    if dest.stat().st_size < 1024:
        raise RuntimeError("archivo demasiado pequeño")


def main() -> int:
    username = sys.argv[1] if len(sys.argv) > 1 else USER
    OUT.mkdir(exist_ok=True)
    manifest = OUT / "manifest.json"
    failures = OUT / "fallidas.json"
    progress = OUT / "progreso.txt"

    done = {}
    if manifest.exists():
        done = {item["key"]: item for item in json.loads(manifest.read_text())}

    failed: dict[str, dict] = {}
    if failures.exists():
        failed = {f["key"]: f for f in json.loads(failures.read_text())}

    with sync_playwright() as p:
        # ponytail: PLAYWRIGHT_CHANNEL=chrome en macOS; sin canal usa Chromium del contenedor
        launch = {"headless": True}
        if ch := os.environ.get("PLAYWRIGHT_CHANNEL"):
            launch["channel"] = ch
        browser = p.chromium.launch(**launch)
        page = browser.new_page(user_agent=UA)

        print(f"Obteniendo catálogo de {username}...", flush=True)
        songs = fetch_channel_songs(page, ACCOUNT_ID, username)
        print(f"Total: {len(songs)} canciones", flush=True)

        for i, song in enumerate(songs, 1):
            key = song["performance_key"]
            title = song.get("title") or "sin-titulo"
            artist = song.get("artist") or "desconocido"
            web_url = song.get("web_url") or ""
            recording_url = f"https://www.smule.com{web_url}"

            if key in done and Path(done[key]["file"]).exists():
                if i % 100 == 0:
                    print(f"[{i}/{len(songs)}] {len(done)} descargadas", flush=True)
                continue

            print(f"[{i}/{len(songs)}] {artist} - {title}", flush=True)
            progress.write_text(f"{i}/{len(songs)} - {title}\n")

            try:
                media_url = media_from_page(page, recording_url)
                if not media_url:
                    raise RuntimeError("audio no cargó a tiempo")

                ext = ".mp4" if media_url.endswith(".mp4") else ".m4a"
                filename = f"{slugify(artist)}--{slugify(title)}--{key}{ext}"
                dest = OUT / filename
                download_media(media_url, dest)

                done[key] = {
                    "key": key,
                    "title": title,
                    "artist": artist,
                    "recording_url": recording_url,
                    "media_url": media_url,
                    "file": str(dest),
                }
                manifest.write_text(
                    json.dumps(list(done.values()), ensure_ascii=False, indent=2)
                )
                failed.pop(key, None)
                failures.write_text(
                    json.dumps(list(failed.values()), ensure_ascii=False, indent=2)
                )
                time.sleep(0.4)
            except Exception as exc:
                print(f"  sin audio: {exc}", flush=True)
                failed[key] = {
                    "key": key, "title": title, "artist": artist, "url": recording_url,
                }
                failures.write_text(
                    json.dumps(list(failed.values()), ensure_ascii=False, indent=2)
                )

        browser.close()

    ok = sum(1 for item in done.values() if Path(item["file"]).exists())
    print(f"Listo: {ok}/{len(songs)} en {OUT}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
