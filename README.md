# TubiShift

A custom TV channel builder for [Tubi](https://tubitv.com). Add shows to your personal channel, generate a randomized episode queue, and watch on Tubi with automatic episode-to-episode advancement.

```
tubishift/               ← Python server + web UI
├── server.py
├── tubi_scraper.py
├── tray.py
├── build.py
├── requirements.txt
└── static/
    └── index.html
└── tubishift-extension/      ← Chrome extension
    ├── manifest.json
    ├── content.js
    ├── background.js
    ├── popup.html
    └── popup.js
```

---

## How It Works

1. **Search** Tubi's library and add TV series to your channel
2. **Launch Channel** builds a randomized queue — episodes from each show are interleaved so shows rotate (e.g. S1E3 of show A → S2E7 of show B → S3E2 of show C → ...)
3. The **Now Playing** tab shows the current episode with a direct link to open it on Tubi
4. The **Chrome extension** runs in the background while you watch — it automatically navigates to the next episode in your queue when the current one ends, suppressing Tubi's own autoplay so it doesn't interfere
5. Your queue position is saved to the database — close and reopen the app and it resumes exactly where you left off

---

## Running from Source

### Prerequisites

- Python 3.10+
- Google Chrome (for the extension)

### 1. Install Python dependencies

```bash
cd tubishift2
pip install -r requirements.txt
```

For building the `.exe` you'll also need:

```bash
pip install pyinstaller pystray pillow
```

### 2. Start the server

```bash
python server.py
```

Then open **http://localhost:5000** in your browser.

> The server stores `tubishift.db` and `cookies.txt` next to `server.py` when running from source.

### 3. Install the Chrome extension

From the **Get Extension** button in the app header, or manually:

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer mode** (toggle in the top-right)
3. Click **Load unpacked** and select the `tubishift-extension/` folder
4. The 📺 TubiShift icon will appear in your toolbar

---

## Authentication

Tubi's API requires a browser session cookie. On first run, the app will prompt you automatically.

**To set up manually:**

1. Go to [tubitv.com](https://tubitv.com) in Chrome and log in (or browse as guest)
2. Press `F12` → **Application** tab → **Cookies** → `https://tubitv.com`
3. Find the cookie named `at`, double-click its **Value** column to select it
4. Paste it into the cookie field in the app

Cookies are saved to `cookies.txt` (in `%APPDATA%\TubiShift\` when running as `.exe`, or next to `server.py` in dev). If you start getting 401 errors, your cookie has expired — just repeat the setup.

---

## Building the Windows .exe

The app can be packaged into a single `TubiShift.exe` that users can run without installing Python.

```bash
cd tubishift2
python build.py
```

Output: `tubishift2/dist/TubiShift.exe`

**What the build does:**

- Bundles the Flask server, scraper, and all dependencies into one file via PyInstaller
- Embeds the `static/` web UI folder as a resource
- Embeds the `tubishift-extension/` folder so the in-app download button works
- Produces a windowed app (no console) with a system tray icon

**User data when running as .exe:**

| File | Location |
|------|----------|
| `tubishift.db` | `%APPDATA%\TubiShift\tubishift.db` |
| `cookies.txt` | `%APPDATA%\TubiShift\cookies.txt` |

These persist across updates — replacing `TubiShift.exe` with a new build won't lose the user's channel or queue.

**Distributing:**

Ship `TubiShift.exe` as a standalone file. The extension is bundled inside and downloadable via the **Get Extension** button in the UI. Users do not need Python installed.

---

## Project Structure

### Server (`server.py`)

Flask app running on `localhost:5000`. Handles:

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/channel` | GET | List all shows in the channel |
| `/api/channel/add` | POST | Add a show (fetches all episodes) |
| `/api/channel/remove/<id>` | DELETE | Remove a show |
| `/api/channel/clear` | DELETE | Remove all shows and reset queue |
| `/api/channel/queue` | GET | Load or build the episode queue |
| `/api/channel/queue/reset` | POST | Discard saved queue (next launch builds fresh) |
| `/api/channel/advance` | POST | Advance queue pointer, return next URL |
| `/api/channel/extension/status` | GET | Current queue position and active state |
| `/api/channel/extension/active` | POST | Toggle auto-advance on/off |
| `/api/channel/extension/get_credits_secs` | POST | Credits timestamp for current video |
| `/api/auth/status` | GET | Whether a valid cookie is loaded |
| `/api/auth/cookies` | POST | Save a new cookie |
| `/api/extension/download` | GET | Download the extension as a `.zip` |

### Scraper (`tubi_scraper.py`)

Talks to Tubi's production CDN APIs:

- **Search:** `https://search.production-public.tubi.io/api/v2/search`
- **Episodes:** `https://content-cdn.production-public.tubi.io/api/v2/content`

Authentication uses the `at` cookie as a Bearer token. Can also be used as a CLI tool:

```bash
# Search
python tubi_scraper.py search "Futurama"

# Fetch all episodes for a series
python tubi_scraper.py episodes 300001234

# Save episodes to JSON
python tubi_scraper.py episodes 300001234 --out futurama.json

# Auto-extract cookies from your browser (requires browser-cookie3)
python tubi_scraper.py --get-cookies
```

### Tray app (`tray.py`)

Entry point for the `.exe`. Starts Flask in a daemon thread, patches all file paths to AppData, then runs a `pystray` system tray icon with Open and Quit menu items. Falls back gracefully if `pystray` isn't available.

### Database (`tubishift.db`)

SQLite with WAL mode. Three tables:

| Table | Contents |
|-------|----------|
| `shows` | Series added to the channel (id, title, poster) |
| `episodes` | All episodes for each show (title, season, episode, duration, credits timestamp, Tubi URL) |
| `queue_state` | Singleton row — the current queue JSON, position, and episodes-per-show setting |

### Chrome Extension (`tubishift-extension/`)

| File | Purpose |
|------|---------|
| `manifest.json` | MV3 manifest — permissions for tubitv.com and localhost:5000 |
| `content.js` | Runs at `document_idle` on Tubi video pages — watches `currentTime`, advances at the credits timestamp, suppresses Tubi's autoplay overlay via CSS |
| `background.js` | Service worker — proxies requests from content scripts to the local server (required because content scripts can't fetch `http://localhost` from `https` pages) |
| `popup.html/js` | Toolbar popup showing queue status and an on/off toggle |