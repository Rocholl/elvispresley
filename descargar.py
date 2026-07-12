#!/usr/bin/env python3
"""Descarga grabaciones de un perfil de Smule (canal completo)."""

import json
import logging
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
LOAD_TIMEOUT_S = int(os.environ.get("LOAD_TIMEOUT_S", "120"))
log = logging.getLogger("descargar")


def setup_logging(out: Path) -> None:
    out.mkdir(exist_ok=True)
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for handler in (
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(out / "descarga.log", encoding="utf-8"),
    ):
        handler.setFormatter(fmt)
        log.addHandler(handler)


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
            log.info("Catálogo en caché: %d canciones", len(songs))
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
            log.info("  listando... %d", len(songs))
        if len(batch) < API_LIMIT:
            break
        time.sleep(0.12)

    catalog.write_text(json.dumps(songs, ensure_ascii=False, indent=2))
    return songs


MEDIA_RE = re.compile(r"https://c-cf\.cdn\.smule\.com/.+?\.(?:m4a|mp4)")


def resolve_file(item: dict) -> Path:
    """Path local; el manifest puede traer rutas absolutas de otro equipo."""
    name = Path(item.get("file") or "").name
    return OUT / name if name else OUT / f"{item.get('key', 'sin-key')}.m4a"


def file_ok(path: Path) -> bool:
    return path.exists() and path.stat().st_size >= 1024


def media_from_fetch(page, performance_key: str) -> str | None:
    found = page.evaluate(
        """async (key) => {
          const cdn = /https:\\/\\/c-cf\\.cdn\\.smule\\.com\\/[^"'\\s]+\\.(m4a|mp4)/;
          const pick = (obj) => {
            if (!obj) return null;
            for (const k of ['video_media_mp4_url', 'media_url', 'video_media_url']) {
              const v = obj[k];
              if (typeof v === 'string' && cdn.test(v)) return v.match(cdn)[0];
            }
            return null;
          };
          const urls = [
            `https://www.smule.com/api/recording/${key}`,
            `https://www.smule.com/api/performance/${key}`,
          ];
          for (const u of urls) {
            try {
              const r = await fetch(u, {headers: {Accept: 'application/json'}});
              const text = await r.text();
              const m = text.match(cdn);
              if (m) return m[0];
              try {
                const j = JSON.parse(text);
                return pick(j.performance || j.recording || j.list?.[0] || j);
              } catch {}
            } catch {}
          }
          return null;
        }""",
        performance_key,
    )
    return found if found and MEDIA_RE.search(found) else None


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
        'button[aria-label*="play"]',
        ".vjs-big-play-button",
        "button.vjs-play-control",
        ".play-button",
        '[data-testid="play-button"]',
    ):
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.click(timeout=2000)
                return
            except Exception:
                pass
    try:
        page.locator("video").first.click(timeout=1000)
    except Exception:
        pass


def _pick_media(page, captured: list[str]) -> str | None:
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
        """() => {
          const p = window.DataStore?.Pages?.Recording?.performance;
          if (!p) return '';
          for (const k of ['video_media_mp4_url', 'media_url', 'video_media_url']) {
            const v = p[k];
            if (typeof v === 'string' && v.includes('cdn.smule.com')) return v;
          }
          return '';
        }"""
    )
    if isinstance(store_mu, str) and MEDIA_RE.search(store_mu):
        return store_mu
    return None


def media_from_page(page, recording_url: str, performance_key: str, timeout_s: int = LOAD_TIMEOUT_S) -> str | None:
    found = media_from_fetch(page, performance_key)
    if found:
        log.info("  audio vía API")
        return found

    captured: list[str] = []

    def on_response(response):
        if MEDIA_RE.search(response.url):
            captured.append(response.url)

    page.on("response", on_response)
    try:
        page.goto(recording_url, wait_until="domcontentloaded", timeout=60000)
        dismiss_cookies(page)
        found = _pick_media(page, captured)
        if found:
            log.info("  audio en HTML inicial")
            return found

        try:
            page.wait_for_load_state("load", timeout=30000)
        except Exception:
            pass
        found = _pick_media(page, captured)
        if found:
            return found

        deadline = time.time() + timeout_s
        play_attempts = 0
        reloaded = False
        while time.time() < deadline:
            found = _pick_media(page, captured)
            if found:
                return found

            elapsed = timeout_s - (deadline - time.time())
            if not reloaded and elapsed > timeout_s * 0.5:
                log.info("  recargando página...")
                page.reload(wait_until="domcontentloaded", timeout=60000)
                dismiss_cookies(page)
                try_play(page)
                reloaded = True
                page.wait_for_timeout(3000)
                continue

            if play_attempts < 8 and elapsed > 3 * (play_attempts + 1):
                try_play(page)
                play_attempts += 1

            page.wait_for_timeout(1500)

        return None
    finally:
        page.remove_listener("response", on_response)


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
    setup_logging(OUT)
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
        # ponytail: HEADLESS=false + xvfb en Docker evita bloqueos de Smule al headless
        headless = os.environ.get("HEADLESS", "true").lower() not in ("0", "false", "no")
        launch = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }
        if ch := os.environ.get("PLAYWRIGHT_CHANNEL"):
            launch["channel"] = ch
        browser = p.chromium.launch(**launch)
        page = browser.new_page(user_agent=UA)
        page.set_viewport_size({"width": 1280, "height": 720})

        log.info("Obteniendo catálogo de %s...", username)
        songs = fetch_channel_songs(page, ACCOUNT_ID, username)
        already = sum(1 for item in done.values() if file_ok(resolve_file(item)))
        log.info("Total: %d canciones (%d ya descargadas)", len(songs), already)

        for i, song in enumerate(songs, 1):
            key = song["performance_key"]
            title = song.get("title") or "sin-titulo"
            artist = song.get("artist") or "desconocido"
            web_url = song.get("web_url") or ""
            recording_url = f"https://www.smule.com{web_url}"

            if key in done and file_ok(resolve_file(done[key])):
                if i % 100 == 0:
                    log.info("[%d/%d] %d descargadas (saltando ya hechas)", i, len(songs), already)
                continue

            log.info("[%d/%d] %s - %s", i, len(songs), artist, title)
            progress.write_text(f"{i}/{len(songs)} - {title}\n")

            try:
                media_url = None
                dest = None
                prev = done.get(key)

                # Reutilizar URL del manifest (las rutas de Mac no existen en el VPS)
                if prev and (mu := prev.get("media_url")) and MEDIA_RE.search(mu):
                    dest = resolve_file(prev)
                    if not file_ok(dest):
                        log.info("  redescargando desde manifest...")
                        download_media(mu, dest)
                    media_url = mu

                if not media_url:
                    for attempt in range(1, 3):
                        media_url = media_from_page(page, recording_url, key)
                        if media_url:
                            break
                        if attempt < 2:
                            log.info("  reintento %d/2...", attempt + 1)
                            page.wait_for_timeout(2000)
                if not media_url:
                    raise RuntimeError("audio no cargó a tiempo")

                if not dest:
                    ext = ".mp4" if media_url.endswith(".mp4") else ".m4a"
                    dest = OUT / f"{slugify(artist)}--{slugify(title)}--{key}{ext}"
                    download_media(media_url, dest)
                size_kb = dest.stat().st_size // 1024
                log.info("  OK %s (%d KB) — %d/%d", dest.name, size_kb, len(done) + 1, len(songs))

                done[key] = {
                    "key": key,
                    "title": title,
                    "artist": artist,
                    "recording_url": recording_url,
                    "media_url": media_url,
                    "file": dest.name,
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
                log.warning("  FALLO: %s", exc)
                failed[key] = {
                    "key": key, "title": title, "artist": artist, "url": recording_url,
                }
                failures.write_text(
                    json.dumps(list(failed.values()), ensure_ascii=False, indent=2)
                )

        browser.close()

    ok = sum(1 for item in done.values() if file_ok(resolve_file(item)))
    log.info("Listo: %d/%d en %s", ok, len(songs), OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
