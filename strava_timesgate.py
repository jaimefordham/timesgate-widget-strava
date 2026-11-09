#!/usr/bin/env python3
"""
strava_timesgate.py

Fetch year-to-date (YTD) cycling statistics from the Strava API and display
them on one screen of a Divoom Times Gate.

Layout (128x128):
    [bike icon]  Year  [Strava logo]
    ---------------------------------
    1,234 km            distance
    56 rides            ride count
    78h 12m             moving time
    9,876 m             elevation gain
    updated 07:30

Usage:
    python strava_timesgate.py --auth            # one-time Strava OAuth setup
    python strava_timesgate.py                   # fetch + push to the device
    python strava_timesgate.py --debug           # fetch + print everything, don't push
    python strava_timesgate.py --preview out.png # render to file, don't push
    python strava_timesgate.py --demo --debug    # fake data, no Strava, no device
    python strava_timesgate.py --screen 2        # override the screen (0-4)

Dependencies: requests, Pillow  (pip install requests pillow)
See README.md for full setup.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"
DEFAULT_TOKENS = SCRIPT_DIR / "strava_tokens.json"

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API = "https://www.strava.com/api/v3"

SIZE = 128  # Times Gate LCD resolution (per screen)
STRAVA_ORANGE = (252, 76, 2)

DEBUG = False  # set by --debug


def debug(msg: str = "") -> None:
    """Print only when --debug is active."""
    if DEBUG:
        print(f"[debug] {msg}" if msg else "")


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
DEFAULTS = {
    "strava_client_id": "",
    "strava_client_secret": "",
    "device_ip": "192.168.1.50",
    "device_endpoint": "/post",       # "/divoom_api" on some HW revisions
    "device_port": 80,                # 9000 on some HW revisions
    "local_token": None,              # integer from Divoom app, if required
    "screen": 0,                      # 0-4, left to right
    "units": "metric",                # "metric" or "imperial"
    "logo_path": "strava_logo.png",   # official Strava brand asset (optional)
    "bike_icon_path": "",             # optional custom bike PNG
    "font_path": "",                  # optional TTF; auto-detected if blank
    "jpeg_quality": 90,
    "tokens_path": str(DEFAULT_TOKENS),
}

SECRET_KEYS = {"strava_client_secret", "local_token"}


def load_config(path: Path) -> dict:
    cfg = dict(DEFAULTS)
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    return cfg


def mask(value) -> str:
    s = str(value)
    if value in (None, ""):
        return repr(value)
    return s[:2] + "*" * max(0, len(s) - 4) + s[-2:] if len(s) > 4 else "****"


# --------------------------------------------------------------------------
# Strava OAuth + API
# --------------------------------------------------------------------------
def strava_auth(cfg: dict) -> None:
    """One-time interactive OAuth flow. Saves access + refresh tokens."""
    if not cfg["strava_client_id"] or not cfg["strava_client_secret"]:
        sys.exit("Set strava_client_id and strava_client_secret in config.json first.")

    params = {
        "client_id": cfg["strava_client_id"],
        "redirect_uri": "http://localhost/exchange_token",
        "response_type": "code",
        "approval_prompt": "force",
        "scope": "read,activity:read",
    }
    url = f"{STRAVA_AUTH_URL}?{urlencode(params)}"
    print("\n1. Open this URL and click 'Authorize':\n")
    print(f"   {url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print("2. The browser will redirect to a localhost page that fails to load.")
    print("   That's expected. Copy the FULL URL from the address bar.\n")
    redirect = input("Paste the redirected URL here: ").strip()

    code = parse_qs(urlparse(redirect).query).get("code", [None])[0]
    if not code:
        sys.exit("No 'code' parameter found in that URL.")

    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": cfg["strava_client_id"],
        "client_secret": cfg["strava_client_secret"],
        "code": code,
        "grant_type": "authorization_code",
    }, timeout=20)
    resp.raise_for_status()
    tokens = resp.json()
    save_tokens(cfg, tokens)
    athlete = tokens.get("athlete", {})
    print(f"\nAuthorised as {athlete.get('firstname', '')} {athlete.get('lastname', '')}"
          f" (id {athlete.get('id')}). Tokens saved to {cfg['tokens_path']}.")


def save_tokens(cfg: dict, tokens: dict) -> None:
    path = Path(cfg["tokens_path"])
    keep = {k: tokens[k] for k in ("access_token", "refresh_token", "expires_at") if k in tokens}
    if "athlete" in tokens and tokens["athlete"].get("id"):
        keep["athlete_id"] = tokens["athlete"]["id"]
    elif tokens.get("athlete_id"):
        keep["athlete_id"] = tokens["athlete_id"]
    elif path.exists():
        old = json.loads(path.read_text())
        if "athlete_id" in old:
            keep["athlete_id"] = old["athlete_id"]
    path.write_text(json.dumps(keep, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def get_access_token(cfg: dict) -> tuple[str, dict]:
    """Return a valid access token, refreshing it if expired.

    Strava rotates refresh tokens, so the new one is always persisted.
    """
    path = Path(cfg["tokens_path"])
    if not path.exists():
        sys.exit("No Strava tokens found. Run with --auth first.")
    tokens = json.loads(path.read_text())

    remaining = int(tokens.get("expires_at", 0) - time.time())
    debug(f"Access token expires in {remaining} s")
    if remaining < 300:
        debug("Refreshing access token")
        resp = requests.post(STRAVA_TOKEN_URL, data={
            "client_id": cfg["strava_client_id"],
            "client_secret": cfg["strava_client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        }, timeout=20)
        debug(f"POST {STRAVA_TOKEN_URL} -> HTTP {resp.status_code}")
        resp.raise_for_status()
        new = resp.json()
        new["athlete_id"] = tokens.get("athlete_id")
        save_tokens(cfg, new)
        tokens = json.loads(path.read_text())
        debug(f"New token expires at {datetime.fromtimestamp(tokens['expires_at'])}")

    return tokens["access_token"], tokens


def strava_get(url: str, headers: dict) -> requests.Response:
    r = requests.get(url, headers=headers, timeout=20)
    debug(f"GET {url} -> HTTP {r.status_code}")
    if DEBUG:
        usage = r.headers.get("X-RateLimit-Usage") or r.headers.get("X-ReadRateLimit-Usage")
        limit = r.headers.get("X-RateLimit-Limit") or r.headers.get("X-ReadRateLimit-Limit")
        if usage:
            debug(f"Strava rate limit usage (15 min, daily): {usage} of {limit}")
    r.raise_for_status()
    return r


STAT_FIELDS = {
    "ytd": "ytd_ride_totals",
    "all-time": "all_ride_totals",
}
MODE_LABELS = {
    "ytd": "Year",
    "all-time": "All time",
}


def fetch_ride_stats(cfg: dict, mode: str) -> dict:
    """Return the selected ride totals for the authenticated athlete.

    Keys: count, distance (m), moving_time (s), elapsed_time (s),
          elevation_gain (m)
    """
    token, tokens = get_access_token(cfg)
    headers = {"Authorization": f"Bearer {token}"}

    athlete_id = tokens.get("athlete_id")
    if not athlete_id:
        athlete_id = strava_get(f"{STRAVA_API}/athlete", headers).json()["id"]
        tokens["athlete_id"] = athlete_id
        save_tokens(cfg, tokens)
    debug(f"Athlete ID: {athlete_id}")

    stats = strava_get(f"{STRAVA_API}/athletes/{athlete_id}/stats", headers).json()
    return stats[STAT_FIELDS[mode]]


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",       # macOS
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",                            # Windows
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",    # Debian/Ubuntu/RPi
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",  # Fedora
]


def load_font(cfg: dict, size: int) -> ImageFont.ImageFont:
    paths = [cfg["font_path"]] if cfg.get("font_path") else []
    for p in paths + FONT_CANDIDATES:
        if p and Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def draw_bicycle(w: int, h: int, colour=(255, 255, 255)) -> Image.Image:
    """Simple line-art bicycle, drawn at 4x and downsampled for smooth edges."""
    s = 4
    W, H = w * s, h * s
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = max(2, int(1.6 * s))
    r = int(H * 0.30)                              # wheel radius
    rear = (r + lw, H - r - lw)                    # rear hub
    front = (W - r - lw, H - r - lw)               # front hub
    crank = (int(W * 0.45), rear[1])               # bottom bracket
    seat = (int(W * 0.36), int(H * 0.22))          # top of seat tube
    head = (int(W * 0.70), int(H * 0.25))          # head tube

    for hub in (rear, front):
        d.ellipse([hub[0] - r, hub[1] - r, hub[0] + r, hub[1] + r], outline=colour, width=lw)
    for a, b in [(rear, crank), (crank, seat), (seat, rear), (seat, head),
                 (head, crank), (head, front)]:
        d.line([a, b], fill=colour, width=lw)
    # saddle and handlebar
    d.line([(seat[0] - 3 * s, seat[1] - 2 * s), (seat[0] + 4 * s, seat[1] - 2 * s)], fill=colour, width=lw)
    d.line([head, (head[0] + 3 * s, head[1] - 4 * s)], fill=colour, width=lw)
    return img.resize((w, h), Image.LANCZOS)


def load_icon(path: str, w: int, h: int) -> Image.Image | None:
    p = Path(path) if path else None
    if p and not p.is_absolute():
        p = SCRIPT_DIR / p
    if p and p.exists():
        icon = Image.open(p).convert("RGBA")
        icon.thumbnail((w, h), Image.LANCZOS)
        return icon
    return None


def fmt_int(n: float) -> str:
    return f"{int(round(n)):,}"


def display_rows(stats: dict, cfg: dict) -> list[tuple[str, str]]:
    """The (value, unit) pairs shown on screen. Shared by render() and --debug."""
    imperial = cfg["units"] == "imperial"
    dist = stats["distance"] / (1609.344 if imperial else 1000)
    elev = stats["elevation_gain"] * (3.28084 if imperial else 1)
    hrs, mins = divmod(int(stats["moving_time"]) // 60, 60)
    return [
        (fmt_int(dist), "mi" if imperial else "km"),
        (fmt_int(stats["count"]), "rides"),
        (f"{hrs:,}h {mins:02d}m", "time"),
        (fmt_int(elev), "ft" if imperial else "m"),
    ]


def render(stats: dict, cfg: dict, mode: str) -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    d = ImageDraw.Draw(img)

    # Header: bike | selected period | Strava logo
    hdr_h = 26
    d.rectangle([0, 0, SIZE, hdr_h], fill=(25, 25, 25))
    bike = load_icon(cfg.get("bike_icon_path", ""), 30, 20) or draw_bicycle(30, 20)
    img.paste(bike, (3, (hdr_h - bike.height) // 2), bike)

    logo = load_icon(cfg.get("logo_path", ""), 26, 20)
    if logo:
        logo_left = SIZE - logo.width - 3
        img.paste(logo, (logo_left, (hdr_h - logo.height) // 2), logo)
    else:
        # Fallback wordmark if no official logo file is provided
        f = load_font(cfg, 8)
        d.text((SIZE - 3, hdr_h // 2), "STRAVA", font=f, fill=STRAVA_ORANGE, anchor="rm")
        logo_left = SIZE - 3 - int(d.textlength("STRAVA", font=f))

    # Centre the selected period between the bike and the logo.
    year_x = (3 + bike.width + logo_left) // 2
    title = MODE_LABELS[mode]
    title_size = 15 if mode == "ytd" else 11
    d.text((year_x, hdr_h // 2 + 1), title, font=load_font(cfg, title_size),
           fill=(255, 255, 255), anchor="mm")
    d.line([(0, hdr_h), (SIZE, hdr_h)], fill=STRAVA_ORANGE, width=2)

    # Stat rows
    big = load_font(cfg, 17)
    small = load_font(cfg, 9)
    y = hdr_h + 6
    for i, (value, unit) in enumerate(display_rows(stats, cfg)):
        colour = STRAVA_ORANGE if i == 0 else (255, 255, 255)
        d.text((5, y + 16), value, font=big, fill=colour, anchor="ls")
        x = 5 + d.textlength(value, font=big) + 3
        d.text((x, y + 16), unit, font=small, fill=(150, 150, 150), anchor="ls")
        y += 22

    d.text((SIZE // 2, SIZE - 2), f"updated {datetime.now():%H:%M}", font=load_font(cfg, 8),
           fill=(100, 100, 100), anchor="mb")
    return img


# --------------------------------------------------------------------------
# Times Gate
# --------------------------------------------------------------------------
def device_url(cfg: dict) -> str:
    port = int(cfg["device_port"])
    host = cfg["device_ip"] if port == 80 else f"{cfg['device_ip']}:{port}"
    return f"http://{host}{cfg['device_endpoint']}"


def build_payload(img: Image.Image, cfg: dict, screen: int) -> dict:
    """Build the Draw/SendHttpGif payload for one screen."""
    if not 0 <= screen <= 4:
        raise ValueError("screen must be 0-4")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=int(cfg["jpeg_quality"]))
    lcd_array = [0] * 5
    lcd_array[screen] = 1

    payload = {
        "Command": "Draw/SendHttpGif",
        "LcdArray": lcd_array,
        "PicNum": 1,
        "PicWidth": SIZE,
        "PicOffset": 0,
        "PicID": int(time.time()),     # must be unique; device caches by ID
        "PicSpeed": 1000,
        "PicData": base64.b64encode(buf.getvalue()).decode("ascii"),
    }
    if cfg.get("local_token") is not None:
        payload["LocalToken"] = int(cfg["local_token"])
    return payload


def push_to_times_gate(payload: dict, cfg: dict) -> dict:
    r = requests.post(device_url(cfg), json=payload, timeout=10)
    r.raise_for_status()
    result = r.json()
    if result.get("error_code") not in (0, None):
        raise RuntimeError(f"Times Gate error: {result}")
    return result


# --------------------------------------------------------------------------
# Debug output
# --------------------------------------------------------------------------
def print_debug_report(cfg: dict, stats: dict, payload: dict, source: str, mode: str) -> None:
    line = "-" * 60
    print(line)
    print("DEBUG MODE: nothing has been sent to the Times Gate")
    print(line)

    print("\nConfig (secrets masked):")
    for k in sorted(cfg):
        v = mask(cfg[k]) if k in SECRET_KEYS else cfg[k]
        print(f"  {k:<22} {v}")

    print(f"\nStrava {STAT_FIELDS[mode]} ({source}):")
    print("  " + json.dumps(stats, indent=2).replace("\n", "\n  "))

    print("\nAs displayed:")
    print(f"  Heading                {MODE_LABELS[mode]}")
    for value, unit in display_rows(stats, cfg):
        print(f"  {unit:<22} {value}")

    pic_bytes = len(base64.b64decode(payload["PicData"]))
    shown = dict(payload)
    shown["PicData"] = f"<{len(payload['PicData'])} base64 chars, {pic_bytes} byte JPEG>"
    if "LocalToken" in shown:
        shown["LocalToken"] = mask(shown["LocalToken"])

    print("\nWould POST to:")
    print(f"  {device_url(cfg)}")
    print(f"  Target screen: {payload['LcdArray'].index(1)}  (LcdArray {payload['LcdArray']})")
    print("\nPayload:")
    print("  " + json.dumps(shown, indent=2).replace("\n", "\n  "))
    print(line)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    global DEBUG
    ap = argparse.ArgumentParser(description="Show Strava cycling stats on a Divoom Times Gate.")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--auth", action="store_true", help="run one-time Strava OAuth")
    ap.add_argument("--mode", choices=STAT_FIELDS, default="ytd",
                    help="stats period: ytd (default) or all-time")
    ap.add_argument("--screen", type=int, help="Times Gate screen 0-4 (overrides config)")
    ap.add_argument("--preview", type=Path, help="save rendered PNG to this path")
    ap.add_argument("--no-push", action="store_true", help="don't send to the device")
    ap.add_argument("--debug", action="store_true",
                    help="print fetched data and the device payload instead of pushing")
    ap.add_argument("--demo", action="store_true", help="use sample data instead of Strava")
    args = ap.parse_args()
    DEBUG = args.debug

    cfg = load_config(args.config)
    debug(f"Config file: {args.config} ({'found' if args.config.exists() else 'not found, using defaults'})")
    if args.auth:
        strava_auth(cfg)
        return

    if args.demo:
        source = "demo data"
        stats = {"count": 87, "distance": 3456789.0, "moving_time": 512345,
                 "elapsed_time": 560000, "elevation_gain": 28765.0}
    else:
        source = "live from Strava"
        stats = fetch_ride_stats(cfg, args.mode)

    screen = args.screen if args.screen is not None else int(cfg["screen"])
    img = render(stats, cfg, args.mode)
    payload = build_payload(img, cfg, screen)

    if args.preview:
        img.resize((SIZE * 4, SIZE * 4), Image.NEAREST).save(args.preview)
        print(f"Preview saved to {args.preview}")

    if args.debug:
        print_debug_report(cfg, stats, payload, source, args.mode)
        return

    if not (args.no_push or args.preview):
        push_to_times_gate(payload, cfg)
        print(f"Sent to Times Gate screen {screen}: {stats['count']} rides, "
              f"{stats['distance'] / 1000:.0f} km")


if __name__ == "__main__":
    main()
