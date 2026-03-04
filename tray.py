"""
tray.py — TubiShift tray application
Starts the Flask server in a background thread and shows a system tray icon.
Bundle with PyInstaller to produce a single .exe.

CLI flags:
  --silent    Start without opening the browser (used by the login startup entry)
"""

import sys
import os
import threading
import webbrowser
import time

# ─── PATH SETUP ───────────────────────────────────────────────────────────────
# When bundled by PyInstaller, files are extracted to sys._MEIPASS.
# When running normally, use the script's directory.

def resource_path(relative):
    """Get absolute path to a bundled resource."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def data_path(relative):
    """
    Get path for user data files (db, cookies, prefs).
    Uses %APPDATA%/TubiShift on Windows, ~/.tubishift on Mac/Linux.
    Created automatically on first run.
    """
    if os.name == "nt":
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "TubiShift")
    else:
        base = os.path.join(os.path.expanduser("~"), ".tubishift")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, relative)


# ─── LAUNCH AT LOGIN ──────────────────────────────────────────────────────────

STARTUP_NAME = "TubiShift"


def get_exe_path() -> str:
    """Return the path to the running executable."""
    return sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)


def launch_at_login_enabled() -> bool:
    """Return True if TubiShift is registered to launch at login."""
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ,
            )
            winreg.QueryValueEx(key, STARTUP_NAME)
            winreg.CloseKey(key)
            return True
        except (ImportError, OSError):
            return False
    else:
        # Mac/Linux: use a marker file in the data directory
        return os.path.exists(data_path("launch_at_login"))


def set_launch_at_login(enabled: bool):
    """Register or deregister TubiShift from the system login startup."""
    exe = get_exe_path()
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            if enabled:
                # Pass --silent so it doesn't open the browser on login
                winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, f'"{exe}" --silent')
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_NAME)
                except OSError:
                    pass
            winreg.CloseKey(key)
        except ImportError:
            pass
    else:
        marker = data_path("launch_at_login")
        if enabled:
            open(marker, "w").close()
        elif os.path.exists(marker):
            os.remove(marker)


# ─── FLASK SERVER ─────────────────────────────────────────────────────────────

def start_server():
    """Start Flask in a daemon thread — dies automatically when tray exits."""
    # Patch paths before importing server so it uses correct locations
    import server as srv
    from pathlib import Path

    srv.DATA_DIR = Path(data_path(""))  # e.g. AppData/TubiShift/
    srv.DB_PATH = srv.DATA_DIR / "tubishift.db"
    srv.app.static_folder = resource_path("static")
    srv.EXTENSION_DIR = Path(resource_path("tubishift-extension"))

    # Also patch tubi_scraper cookie path
    import tubi_scraper
    tubi_scraper.COOKIES_FILE = Path(data_path("cookies.txt"))
    tubi_scraper.ensure_authenticated()
    srv.init_db()

    # Suppress Flask's startup banner
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    srv.app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

# Give Flask a moment to start before opening the browser
time.sleep(1.2)

# ─── TRAY ICON ────────────────────────────────────────────────────────────────

# If launched with --silent (i.e. via login startup), don't open the browser
silent = "--silent" in sys.argv

try:
    import pystray
    from PIL import Image as PilImage

    def open_app(icon, item):
        webbrowser.open("http://localhost:5000")

    def quit_app(icon, item):
        icon.stop()
        os._exit(0)

    def toggle_launch_at_login(icon, item):
        set_launch_at_login(not launch_at_login_enabled())
        # Rebuild the menu so the checkmark updates
        icon.menu = build_menu()

    def build_menu():
        return pystray.Menu(
            pystray.MenuItem("Open TubiShift", open_app, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Launch at Login",
                toggle_launch_at_login,
                checked=lambda item: launch_at_login_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app),
        )

    # Load tray icon image
    icon_path = resource_path(os.path.join("static", "icon_tray.png"))
    if os.path.exists(icon_path):
        img = PilImage.open(icon_path)
    else:
        # Fallback: generate a simple orange circle programmatically
        img = PilImage.new("RGBA", (64, 64), (0, 0, 0, 0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.ellipse([0, 0, 63, 63], fill="#ff5a1f")
        draw.rectangle([14, 18, 50, 40], fill="white")
        draw.rectangle([26, 40, 38, 50], fill="white")
        draw.rectangle([20, 50, 44, 54], fill="white")

    icon = pystray.Icon("TubiShift", img, "TubiShift", build_menu())

    if not silent:
        webbrowser.open("http://localhost:5000")

    icon.run()

except ImportError:
    # pystray not available — just open browser and keep server alive
    if not silent:
        webbrowser.open("http://localhost:5000")
    print("TubiShift running at http://localhost:5000")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass