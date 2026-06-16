"""
OneDrive / local-folder backup sync (Stage 6a).

The "sync" is a one-way push of a whole-file copy of db.sqlite3 to a
configured backup folder, plus a startup check that can pull a newer
remote copy or flag a conflict for the user to resolve.

Bookkeeping that must survive process restarts but is *not* part of the
app data itself lives in a small JSON sidecar file (sync_meta.json) next
to db.sqlite3 — this avoids the chicken-and-egg problem of storing sync
state inside the database whose changes we are tracking.
"""
import json
import shutil
import threading
import time
from pathlib import Path

from django.conf import settings
from django.db import connections
from django.utils import timezone

META_FILENAME = "sync_meta.json"
BACKUP_PREFIX = "pdforge_backup_"
BACKUP_SUFFIX = ".sqlite3"
MAX_BACKUPS = 3

# Set while push() is writing a backup file — lets shutdown_sync() wait for
# an in-flight periodic push to finish before quitting.
_push_in_progress = threading.Event()

_DEFAULT_META = {
    "last_synced_local_version": None,
    "last_synced_remote_mtime": None,
    "last_sync_at": None,
    # not_configured | ok | offline | conflict | error
    "last_sync_status": "not_configured",
}


# ── sidecar state file ──────────────────────────────────────────────────

def _meta_path():
    base = getattr(settings, "APP_DATA_DIR", settings.BASE_DIR)
    return Path(base) / META_FILENAME

def load_meta():
    p = _meta_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            merged = dict(_DEFAULT_META)
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_META)


def save_meta(meta):
    _meta_path().write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── helpers ──────────────────────────────────────────────────────────────

def _db_path():
    return Path(settings.DATABASES["default"]["NAME"])


def _get_settings():
    from .models import AppSettings
    return AppSettings.get()


def folder_configured(app_settings=None):
    app_settings = app_settings or _get_settings()
    return bool(app_settings and app_settings.sync_folder_path)


def folder_reachable(app_settings=None):
    app_settings = app_settings or _get_settings()
    if not folder_configured(app_settings):
        return False
    return Path(app_settings.sync_folder_path).is_dir()


def list_backups(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(folder.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))


def _latest_backup(folder):
    backups = list_backups(folder)
    return backups[-1] if backups else None


def _checkpoint_db():
    """Flush the SQLite WAL so the on-disk file is fully up to date before copying."""
    try:
        with connections["default"].cursor() as cur:
            cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception:
        pass


# ── status (read-only, safe to call on every page render) ───────────────

def get_status(app_settings=None):
    app_settings = app_settings or _get_settings()
    meta = load_meta()

    if not folder_configured(app_settings):
        return {
            "configured": False, "reachable": False, "conflict": False,
            "local_changed": False, "remote_changed": False,
            "last_sync_at": None, "last_sync_status": "not_configured",
            "backups": [],
        }

    reachable = folder_reachable(app_settings)
    local_changed = remote_changed = conflict = False
    backups = []

    if reachable:
        folder = Path(app_settings.sync_folder_path)
        backups = list_backups(folder)
        backup = backups[-1] if backups else None
        remote_mtime = backup.stat().st_mtime if backup else None
        remote_changed = (remote_mtime != meta.get("last_synced_remote_mtime"))

        current_version = (
            app_settings.data_version.isoformat() if app_settings.data_version else None
        )
        local_changed = (current_version != meta.get("last_synced_local_version"))

        conflict = local_changed and remote_changed

    return {
        "configured": True,
        "reachable": reachable,
        "conflict": conflict,
        "local_changed": local_changed,
        "remote_changed": remote_changed,
        "last_sync_at": meta.get("last_sync_at"),
        "last_sync_status": meta.get("last_sync_status"),
        "backups": backups,
    }


# ── push / pull ──────────────────────────────────────────────────────────

def push(app_settings=None):
    """Copy db.sqlite3 to the backup folder, rotate old backups, update meta."""
    app_settings = app_settings or _get_settings()
    meta = load_meta()

    if not folder_configured(app_settings):
        meta["last_sync_status"] = "not_configured"
        save_meta(meta)
        return {"status": "not_configured"}

    if not folder_reachable(app_settings):
        meta["last_sync_status"] = "offline"
        save_meta(meta)
        return {"status": "offline"}

    _push_in_progress.set()
    try:
        _checkpoint_db()

        folder = Path(app_settings.sync_folder_path)
        ts = timezone.now().strftime("%Y%m%d_%H%M%S")
        dest = folder / f"{BACKUP_PREFIX}{ts}{BACKUP_SUFFIX}"
        shutil.copy2(_db_path(), dest)

        for old in list_backups(folder)[:-MAX_BACKUPS]:
            try:
                old.unlink()
            except OSError:
                pass

        meta["last_synced_local_version"] = (
            app_settings.data_version.isoformat() if app_settings.data_version else None
        )
        meta["last_synced_remote_mtime"] = dest.stat().st_mtime
        meta["last_sync_at"] = timezone.now().isoformat()
        meta["last_sync_status"] = "ok"
        save_meta(meta)
        return {"status": "ok", "backup": str(dest)}
    finally:
        _push_in_progress.clear()


def pull(app_settings=None):
    """Overwrite local db.sqlite3 with the latest backup from the folder."""
    app_settings = app_settings or _get_settings()
    folder = Path(app_settings.sync_folder_path)
    backup = _latest_backup(folder)
    if not backup:
        return {"status": "no_backup"}

    connections.close_all()
    shutil.copy2(backup, _db_path())

    from .models import AppSettings
    new_settings = AppSettings.get()

    meta = load_meta()
    meta["last_synced_local_version"] = (
        new_settings.data_version.isoformat() if new_settings.data_version else None
    )
    meta["last_synced_remote_mtime"] = backup.stat().st_mtime
    meta["last_sync_at"] = timezone.now().isoformat()
    meta["last_sync_status"] = "ok"
    save_meta(meta)
    return {"status": "ok"}


# ── startup check (run once per process) ─────────────────────────────────

def startup_check():
    """Returns {"action": "none"|"pulled"|"conflict"|"offline"|"not_configured"}"""
    app_settings = _get_settings()

    if not folder_configured(app_settings):
        return {"action": "not_configured"}

    if not folder_reachable(app_settings):
        meta = load_meta()
        meta["last_sync_status"] = "offline"
        save_meta(meta)
        return {"action": "offline"}

    status = get_status(app_settings)

    if status["conflict"]:
        return {"action": "conflict"}

    if status["remote_changed"] and not status["local_changed"]:
        pull(app_settings)
        return {"action": "pulled"}

    return {"action": "none"}


# ── periodic background push ──────────────────────────────────────────────
# NOTE (dev quirk): Django's `runserver` autoreloader runs two processes —
# a watcher and the actual server (RUN_MAIN=true). apps.py only starts this
# thread in the process that should run it, but if the reloader is ever
# bypassed in an unusual way you may briefly see two threads in dev. This is
# harmless (push is idempotent) and won't happen in the packaged Mac app.

_thread_started = threading.Event()


def _periodic_loop():
    while True:
        try:
            app_settings = _get_settings()
            interval = max(1, app_settings.sync_interval_minutes or 15)
            if (
                app_settings.sync_auto_enabled
                and folder_configured(app_settings)
                and folder_reachable(app_settings)
            ):
                status = get_status(app_settings)
                if status["local_changed"] and not status["conflict"]:
                    push(app_settings)
        except Exception:
            # Sync issues surface via the status badge / БД page, not crashes.
            pass
        time.sleep(interval * 60)


def start_periodic_sync():
    """Start the background push thread once per process."""
    if _thread_started.is_set():
        return
    _thread_started.set()
    t = threading.Thread(target=_periodic_loop, name="pdforge-sync", daemon=True)
    t.start()


# ── shutdown (called by run_app.py on quit) ───────────────────────────────

def local_data_changed(app_settings=None):
    """True if local data has changed since the last successful push to a
    configured, reachable backup folder (regardless of the auto-sync toggle)."""
    app_settings = app_settings or _get_settings()
    if not (folder_configured(app_settings) and folder_reachable(app_settings)):
        return False
    status = get_status(app_settings)
    return status["local_changed"] and not status["conflict"]


def has_unsynced_changes(app_settings=None):
    """True if auto-sync is on AND there's unsynced local data — used by the
    quit handler to decide whether to wait/push on close."""
    app_settings = app_settings or _get_settings()
    if not app_settings.sync_auto_enabled:
        return False
    return local_data_changed(app_settings)


def shutdown_sync(timeout=10):
    """Called once on app quit. Waits (up to `timeout`s) for any in-flight
    periodic push to finish, then does a final push if there are unsynced
    local changes. Never raises — quitting must not hang or crash."""
    deadline = time.monotonic() + timeout
    while _push_in_progress.is_set() and time.monotonic() < deadline:
        time.sleep(0.1)

    try:
        if has_unsynced_changes():
            push()
    except Exception:
        pass
