"""
build.py — builds TubiShift.exe using PyInstaller

Run from the tubishift2 folder:
    python build.py

Requirements:
    pip install pyinstaller pystray pillow

Output:
    dist/TubiShift.exe   (single file, ~30-50MB)
    dist/TubiShift/      (also created, can ignore)
"""

import subprocess
import sys
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

def main():
    # Check PyInstaller is available
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    try:
        import pystray
    except ImportError:
        print("pystray not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pystray"])

    # Clean previous build
    for d in ["build", os.path.join("dist", "TubiShift")]:
        if os.path.exists(d):
            shutil.rmtree(d)

    static_dir = os.path.join(HERE, "static")
    ext_dir = os.path.join(HERE, "tubishift-extension")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                        # single .exe
        "--windowed",                       # no console window
        "--name", "TubiShift",
        "--icon", os.path.join(static_dir, "icon_tray.ico"),  # taskbar icon
        # Bundle the static web UI folder
        "--add-data", f"{static_dir}{os.pathsep}static",
        # Bundle the Chrome extension so it can be served for download
        "--add-data", f"{ext_dir}{os.pathsep}tubishift-extension",
        # Hidden imports Flask and friends need
        "--hidden-import", "flask",
        "--hidden-import", "flask_cors",
        "--hidden-import", "werkzeug",
        "--hidden-import", "jinja2",
        "--hidden-import", "click",
        "--hidden-import", "pystray",
        "--hidden-import", "PIL",
        "--hidden-import", "requests",
        "--hidden-import", "tubi_scraper",
        "--hidden-import", "server",
        "tray.py",
    ]

    print("Running PyInstaller...")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=HERE)

    if result.returncode == 0:
        exe = os.path.join(HERE, "dist", "TubiShift.exe")
        if os.path.exists(exe):
            size_mb = os.path.getsize(exe) / 1024 / 1024
            print(f"\n✅ Build successful!")
            print(f"   {exe}  ({size_mb:.1f} MB)")
            print(f"\nDistribute just TubiShift.exe — users double-click to run.")
            print(f"tubishift.db and cookies.txt will be created next to the .exe.")
        else:
            print("\n⚠ Build finished but .exe not found — check dist/ folder.")
    else:
        print("\n❌ Build failed. Check output above.")


if __name__ == "__main__":
    main()