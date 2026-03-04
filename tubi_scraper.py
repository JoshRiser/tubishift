"""
tubi_scraper.py
---------------
Scrapes Tubi's internal API for series search and episode data.

AUTHENTICATION:
Tubi requires a session cookie (connect.sid) + access token (at=...).
The easiest way to get these is to copy them from your browser after
visiting tubitv.com. See README for instructions.

You have two options:
  1. Run with --get-cookies to extract cookies automatically from Chrome/Firefox
  2. Manually paste your cookie string into cookies.txt
"""

import requests
import json
import time
import sys
import os
import re
from pathlib import Path
from typing import Optional

COOKIES_FILE = Path(__file__).parent / "cookies.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://tubitv.com/",
    "Origin": "https://tubitv.com",
    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ─── COOKIE LOADING ──────────────────────────────────────────────────────────

def load_cookies_from_file(path: Path = None) -> bool:
    """Load cookies from a cookies.txt file and inject into SESSION."""
    if path is None:
        path = COOKIES_FILE
    if not path.exists():
        return False

    raw = path.read_text().strip()
    if not raw:
        return False

    # Support two formats:
    # 1. Raw cookie header string: "connect.sid=abc; at=xyz; ..."
    # 2. Netscape/curl format (tab-separated lines)

    cookies = {}

    if "\t" in raw:
        # Netscape format
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    else:
        # Raw cookie header string
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()

    if cookies:
        SESSION.cookies.update(cookies)
        print(f"[auth] Loaded {len(cookies)} cookies from {path.name}")
        return True

    return False


def try_extract_browser_cookies() -> bool:
    """
    Try to extract Tubi cookies from Chrome or Firefox using browser-cookie3.
    Falls back gracefully if the library isn't installed.
    """
    try:
        import browser_cookie3
    except ImportError:
        return False

    for loader, name in [(browser_cookie3.chrome, "Chrome"),
                         (browser_cookie3.firefox, "Firefox")]:
        try:
            jar = loader(domain_name=".tubitv.com")
            cookies = {c.name: c.value for c in jar}
            if "connect.sid" in cookies or "at" in cookies:
                SESSION.cookies.update(cookies)
                print(f"[auth] Loaded Tubi cookies from {name}")
                return True
        except Exception:
            continue

    return False


def ensure_authenticated() -> bool:
    """
    Ensure we have a valid Tubi session. Try methods in order:
    1. cookies.txt file
    2. browser-cookie3 auto-extraction
    3. Prompt user with instructions
    """
    if load_cookies_from_file():
        return True

    if try_extract_browser_cookies():
        # Save for future use
        save_cookies_to_file()
        return True

    print_auth_instructions()
    return False


def save_cookies_to_file():
    """Save current session cookies to cookies.txt."""
    cookie_str = "; ".join(f"{k}={v}" for k, v in SESSION.cookies.items())
    COOKIES_FILE.write_text(cookie_str)
    print(f"[auth] Cookies saved to {COOKIES_FILE}")


def print_auth_instructions():
    print("""
╔══════════════════════════════════════════════════════════════╗
║           TUBI AUTHENTICATION REQUIRED                       ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Tubi requires browser cookies to access its API.           ║
║  Follow these steps:                                         ║
║                                                              ║
║  1. Open Chrome/Firefox and go to https://tubitv.com        ║
║  2. Log in (or just browse as a guest — that works too)      ║
║  3. Press F12 → Application tab → Cookies → tubitv.com      ║
║  4. Find and copy these cookies:                             ║
║       • connect.sid   (required)                             ║
║       • at            (required, the access token)           ║
║       • tubitv-auth   (optional but helpful)                 ║
║                                                              ║
║  5. Create a file called  cookies.txt  next to this script   ║
║     and paste them like this:                                ║
║                                                              ║
║     connect.sid=s%3Axyz...; at=eyJhbG...; tubitv-auth=...   ║
║                                                              ║
║  OR: Install browser-cookie3 to auto-extract:               ║
║     pip install browser-cookie3                              ║
║     (Chrome must be closed first)                            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


# ─── API CALLS ───────────────────────────────────────────────────────────────

def _get(url, params=None, retries=2):
    """GET a Tubi API URL. Returns parsed JSON (dict or list) or None on error."""
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, params=params, timeout=12)
            if resp.status_code == 401:
                print(f"[error] 401 Unauthorized — cookies may be expired or missing.")
                print_auth_instructions()
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.JSONDecodeError:
            return None
        except requests.exceptions.RequestException as e:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"[error] Request failed: {e}", file=sys.stderr)
                return None
    return None


def _extract_url(value) -> str:
    """Safely extract a URL from a field that may be a string, dict, or list of either."""
    if not value:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("url", "")
    return ""


def _parse_item(item: dict) -> dict:
    """Normalise a single Tubi content item into a clean dict."""
    return {
        "id": str(item["id"]),
        "title": item.get("title", "Unknown"),
        "type": item.get("type", "s"),
        "episode_count": item.get("episode_count") or item.get("s_count") or "?",
        "poster_url": _extract_url(item.get("posterarts") or item.get("thumbnails") or ""),
        "description": item.get("description", ""),
        "year": item.get("year"),
    }


def _get_at_token() -> str:
    """Extract the 'at' access token from the session cookies."""
    for cookie in SESSION.cookies:
        if cookie.name == "at":
            return cookie.value
    return ""


def search_series(query: str, limit: int = 20) -> list[dict]:
    """Search Tubi for TV series using the production search API."""
    url = "https://search.production-public.tubi.io/api/v2/search"
    params = {
        "search": query,
        "include_channels": "true",
        "include_linear": "true",
        "is_kids_mode": "false",
        "images[posterarts]": "w408h583_poster",
        "images[landscape_images]": "w978h549_landscape",
    }

    # Try with Bearer token first, fall back to no auth
    at_token = _get_at_token()
    headers = {**SESSION.headers}
    if at_token:
        headers["Authorization"] = f"Bearer {at_token}"

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=12)
        # If auth fails, retry without token
        if resp.status_code in (401, 403) and at_token:
            resp = requests.get(url, params=params, headers=SESSION.headers, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[search] Request failed: {e}", file=sys.stderr)
        return []

    # Response structure:
    #   data["contents"]   — flat map of "0<id>" -> content object
    #   data["containers"] — list with one container, ordered IDs in container["children"]
    if not isinstance(data, dict):
        return []

    contents = data.get("contents") or {}

    # Use container["children"] for ranked order (not container["contents"])
    ordered_ids = []
    for container in (data.get("containers") or []):
        for cid in (container.get("children") or []):
            ordered_ids.append(str(cid))

    seen = set()
    results = []

    def add_item(item):
        if not isinstance(item, dict) or not item.get("id"):
            return
        # Only series (type "s"), not movies/clips (type "v")
        if item.get("type") != "s":
            return
        iid = str(item["id"])
        if iid not in seen:
            seen.add(iid)
            results.append(_parse_item(item))

    # Add in ranked order first
    for oid in ordered_ids:
        item = contents.get(oid)
        if item:
            add_item(item)

    # Then any series not referenced by container
    for item in contents.values():
        add_item(item)

    return results


def _parse_episodes_from_content(content_list: list) -> list[dict]:
    """
    Parse a flat or nested list of Tubi content objects into episode dicts.
    Handles both season-grouped and flat episode lists.
    """
    episodes = []
    for item in content_list:
        if not isinstance(item, dict):
            continue
        # Season container — recurse into children
        if item.get("type") in ("s", "season") or item.get("children"):
            season_num = item.get("season_number") or item.get("number")
            for ep in (item.get("children") or []):
                if not isinstance(ep, dict) or not ep.get("id"):
                    continue
                episodes.append(_build_ep(ep, season_num))
        else:
            # Flat episode
            if item.get("id"):
                episodes.append(_build_ep(item, item.get("season_number")))
    return episodes


def _build_ep(ep: dict, season_num=None) -> dict:
    return {
        "content_id": str(ep["id"]),
        "title": (ep.get("title") or ep.get("episode_name") or
                  f"Episode {ep.get('episode_number', '?')}"),
        "season": ep.get("season_number") or season_num,
        "episode": ep.get("episode_number"),
        "duration_secs": ep.get("duration"),
        "description": ep.get("description", ""),
        "thumbnail": _extract_url(ep.get("thumbnails") or ep.get("posterarts") or ""),
        "tubi_url": f"https://tubitv.com/video/{ep['id']}",
    }


def get_series_episodes(series_id: str) -> list[dict]:
    """
    Fetch all episodes for a Tubi series using the content CDN API.
    Requires the 'at' cookie value as a Bearer token.
    """
    at_token = _get_at_token()
    if not at_token:
        print(f"[episodes] No 'at' token found — cannot fetch episodes.", file=sys.stderr)
        return []

    import uuid
    url = "https://content-cdn.production-public.tubi.io/api/v2/content"
    params = {
        "app_id": "tubitv",
        "platform": "web",
        "content_id": series_id,
        "device_id": str(uuid.uuid4()),
        "include_channels": "true",
        "images[posterarts]": "w408h583_poster",
        "images[landscape_images]": "w978h549_landscape",
    }
    headers = {**SESSION.headers, "Authorization": f"Bearer {at_token}"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[episodes] CDN request failed for {series_id}: {e}", file=sys.stderr)
        return []

    return _parse_cdn_response(data, series_id)


def _parse_cdn_response(data, series_id: str) -> list[dict]:
    """
    Parse the content CDN response.
    The response IS the series object directly (not a map).
    Structure:
      data["type"] == "s"
      data["children"] = [
        { "type": "a", "title": "Season 1", "id": "1", "children": [ <episode objects> ] },
        ...
      ]
    Each episode object has type "v" and all metadata inline.
    """
    if not isinstance(data, dict):
        print(f"[episodes] Unexpected CDN response type: {type(data)}", file=sys.stderr)
        return []

    if data.get("type") not in ("s", "series", "show", None):
        print(f"[episodes] Response is not a series (type={data.get('type')})", file=sys.stderr)
        return []

    episodes = []
    seasons = data.get("children") or []

    for season in seasons:
        if not isinstance(season, dict):
            continue
        # Season containers have type "a"
        season_num = season.get("season_number") or season.get("number") or season.get("id")
        season_eps = season.get("children") or []

        for ep in season_eps:
            if not isinstance(ep, dict):
                continue
            if ep.get("type") not in ("v", "video", "e", "episode"):
                continue
            if not ep.get("id"):
                continue
            episodes.append(_build_ep(ep, season_num))

    return episodes


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Tubi Scraper CLI")
    parser.add_argument("--get-cookies", action="store_true",
                        help="Auto-extract cookies from Chrome/Firefox (requires browser-cookie3)")
    sub = parser.add_subparsers(dest="cmd")

    s = sub.add_parser("search", help="Search Tubi for a series")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)

    e = sub.add_parser("episodes", help="Get all episodes for a series ID")
    e.add_argument("series_id")
    e.add_argument("--out", help="Save to JSON file")

    args = parser.parse_args()

    if args.get_cookies:
        if try_extract_browser_cookies():
            save_cookies_to_file()
        else:
            print("Could not auto-extract cookies. Install browser-cookie3 or use cookies.txt manually.")
        sys.exit(0)

    if not ensure_authenticated():
        sys.exit(1)

    if args.cmd == "search":
        results = search_series(args.query, limit=args.limit)
        if not results:
            print("No results found.")
        else:
            print(f"\n{'ID':<14} {'Episodes':<10} Title")
            print("─" * 60)
            for r in results:
                print(f"{r['id']:<14} {str(r['episode_count']):<10} {r['title']}")

    elif args.cmd == "episodes":
        eps = get_series_episodes(args.series_id)
        if not eps:
            print("No episodes found.")
        else:
            print(f"\n{len(eps)} episodes:\n")
            for ep in eps:
                s_num = ep.get('season', '?')
                e_num = ep.get('episode', '?')
                print(f"  S{s_num}E{str(e_num).zfill(2)}  {ep['title'][:50]}")
                print(f"         {ep['tubi_url']}")

            if args.out:
                with open(args.out, "w") as f:
                    json.dump(eps, f, indent=2)
                print(f"\n✓ Saved to {args.out}")

    else:
        parser.print_help()