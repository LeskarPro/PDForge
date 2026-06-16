#!/usr/bin/env python3
"""
PDForge desktop launcher.

This is the entry point PyInstaller bundles instead of manage.py.
Run directly with `python run_app.py` for a dev-mode dry run — it should
behave like `runserver` but open a native window instead of a browser.
"""
import os
import sys
import shutil
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path

from waitress import serve

# ── 1. Fix WeasyPrint's dlopen() — MUST happen before Django/WeasyPrint
#       are imported (core/views.py imports weasyprint at module level).
if getattr(sys, "frozen", False):
    # Self-contained build: the dylibs WeasyPrint dlopens (libgobject,
    # libpango, libharfbuzz, libfontconfig, libpangoft2, ...) are bundled
    # directly inside the .app (see pdforge.spec `binaries`), so point
    # dlopen at the bundle itself — the target Mac needs no Homebrew.
    os.environ["DYLD_LIBRARY_PATH"] = sys._MEIPASS
    # Fontconfig needs its own config to find fonts; point it at a small
    # bundled config that reads macOS's standard font directories (present
    # on every Mac, so we don't need to ship any fonts ourselves).
    os.environ.setdefault(
        "FONTCONFIG_FILE", str(Path(sys._MEIPASS) / "fontconfig" / "fonts.conf")
    )
else:
    _homebrew_lib = "/opt/homebrew/lib" if os.path.exists("/opt/homebrew/lib") else "/usr/local/lib"
    os.environ.setdefault("DYLD_LIBRARY_PATH", _homebrew_lib)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pdforge.settings")

# `django.conf.settings` is lazy — accessing an attribute loads the
# pdforge.settings module (so settings.APP_DATA_DIR is available) without
# triggering django.setup()/apps.populate() yet.
from django.conf import settings


def ensure_data_dir():
    """First run: copy the seed db into Application Support if missing.

    MUST run before django.setup(). CoreConfig.ready() starts a background
    sync thread that queries the DB immediately when FROZEN. If db.sqlite3
    doesn't exist yet, sqlite3 silently creates an empty file on that
    thread's first connection — which then makes this check think data
    already exists and skip the seed copy, leaving a blank db that
    `migrate` re-seeds from scratch (16 Pests + 15 default Tags + 4
    NonChemicalMeans) instead of the shipping-clean seed.
    """
    data_dir = Path(settings.APP_DATA_DIR)
    db_path = data_dir / "db.sqlite3"
    if db_path.exists():
        return

    resource_dir = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    seed_db = resource_dir / "seed" / "db.sqlite3"
    if seed_db.exists():
        shutil.copy2(seed_db, db_path)


ensure_data_dir()

import django
django.setup()

from django.core.management import call_command
from django.core.wsgi import get_wsgi_application

import webview


def start_server(port=8765):
    call_command("migrate", "--noinput")

    application = get_wsgi_application()
    thread = threading.Thread(
        target=lambda: serve(application, host="127.0.0.1", port=port, threads=4),
        daemon=True,
    )
    thread.start()


class Api:
    """Methods exposed to the frontend as `pywebview.api.<name>(...)`."""

    def __init__(self, port):
        self.port = port

    def _fetch(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url) as resp:
            return resp.read()

    def print_pdf(self, path):
        """Open a PDF in Preview.app for printing (Cmd+P) — avoids the
        window.print()-on-HTML layout bug. Opening a second `webview`
        window for this corrupts pywebview 6.x's JS bridge on the Cocoa
        backend once it's closed, so we hand off to the system PDF viewer
        instead, in a separate process. Written to the OS temp dir purely
        so Preview can open it — nothing is added to the user's data or
        backup folders."""
        data = self._fetch(path)

        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="pdforge_print_")
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        subprocess.run(["open", tmp_path])
        return True

    def save_pdf(self, path, filename="protocol.pdf"):
        """Save the PDF via a native macOS Save panel (folder + filename
        picker), defaulting to ~/Downloads. Falls back to writing straight
        to ~/Downloads if the dialog errors or is cancelled."""
        data = self._fetch(path)

        dest = None
        try:
            downloads = str(Path.home() / "Downloads")
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.SAVE,
                directory=downloads,
                save_filename=filename,
                file_types=("PDF files (*.pdf)",),
            )
            if result:
                picked = result[0] if isinstance(result, (list, tuple)) else result
                dest = str(picked)
        except Exception:
            pass

        if dest is None:
            dest = str(Path.home() / "Downloads" / filename)

        Path(dest).write_bytes(data)
        return dest

    def pick_folder(self, current_path=None):
        """Open a native macOS folder picker (for the backup folder on the
        База данни page). Returns the chosen path, or None if cancelled or
        the dialog errors."""
        start_dir = current_path if current_path and os.path.isdir(current_path) else str(Path.home())
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER,
                directory=start_dir,
            )
        except Exception:
            return None

        if result:
            picked = result[0] if isinstance(result, (list, tuple)) else result
            return str(picked)
        return None


def main():
    port = 8765
    start_server(port)

    api = Api(port)
    window = webview.create_window(
        "PDForge", f"http://127.0.0.1:{port}/",
        js_api=api,
        width=1280, height=860, min_size=(900, 600),
    )

    def on_closing():
        # Runs on the main thread. The backup is a local file copy (typically
        # well under a second), so we do it synchronously and let the window
        # close normally afterwards — no extra threads, no window.destroy()
        # or evaluate_js() from the closing handler, both of which can
        # deadlock pywebview's Cocoa run loop on quit.
        from core import sync_service
        if sync_service.has_unsynced_changes():
            sync_service.shutdown_sync()
        # implicit None return => allow the close to proceed

    window.events.closing += on_closing
    webview.start(debug=False)


if __name__ == "__main__":
    main()