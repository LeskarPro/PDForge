# PDForge

> Desktop application for managing DDD pest-control treatment protocols - generates print-ready PDFs, syncs to OneDrive, and runs as a native macOS app.

<!-- Replace with a real screenshot once taken -->
<!-- ![PDForge protocol list](docs/screenshots/protocol-list.png) -->

---

## What it does

PDForge is a single-user internal tool built for a Bulgarian DDD (Дезинфекция / Дезинсекция / Дератизация) pest-control business. It replaces manual paperwork by letting the operator:

- **Create and manage treatment protocols** - the official two-sided A5 documents required by Bulgarian regulation, filled out per site visit
- **Generate print-ready PDFs** via a custom WeasyPrint template, with support for A5, A5-landscape, and A4 formats
- **Maintain a client and site registry** - clients, locations, contacts, and recurring contracts
- **Log one-off treatments** that don't produce a formal protocol
- **Manage a chemical product catalogue** and pest reference data
- **Back up the database to OneDrive** automatically, with conflict detection and manual sync control
- **Run entirely offline** - no cloud dependency for day-to-day use; OneDrive is backup only

The UI is in Bulgarian.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.2, Python 3.12 |
| Frontend | Django templates, HTMX, Alpine.js |
| PDF generation | WeasyPrint 68 |
| Database | SQLite (with ICU/pysqlite3 for Cyrillic search) |
| Desktop packaging | PyInstaller + pywebview (native macOS window) |
| Sync | OneDrive folder sync via file copy + `sync_meta.json` sidecar |
| Serving (packaged) | Waitress WSGI server on 127.0.0.1 |

No build step — all frontend assets load from CDN (HTMX, Alpine.js, Chart.js).

---

## Key features

- **Protocol editor** - multi-column form covering disinsection, deratization, and disinfection services in one pass; toggle-select pests, inline product table with quantity/concentration, worker assignment, tag system
- **Template system** - save any protocol as a reusable template, organised into folders
- **Print flow** - choose format (A5 / A5-land / A4), preview, print via Preview.app (native Cmd+P), or download PDF via native Save panel — all without leaving the app window
- **OneDrive backup** - periodic background push (configurable interval), auto-pull on startup if remote is newer, conflict resolution UI, manual sync button, quit-time sync for unsaved changes
- **Theme system** - 4 built-in colour themes switchable from Settings, all colours as CSS custom properties
- **Native macOS app** - packaged with PyInstaller + pywebview; ships as a self-contained `.app` with all native library dependencies (Pango, Cairo, HarfBuzz, Fontconfig) bundled - no Homebrew required on the target machine

---

## Design process

The `mockups/` directory contains the iterative HTML mockups built before each implementation stage - from initial shell to the protocol editor. See [`mockups/UI_HANDOFF.md`](mockups/UI_HANDOFF.md) for the handoff notes.

---

## Project structure

```
pdforge/          Django project settings and URLs
core/             Main app - models, views, forms, migrations, template tags
templates/        All Django templates (base shell, protocol editor, PDF template, etc.)
seed/             Blank seed database shipped inside the .app for first-run setup
design/icon/      App icon (SVG source + .icns for macOS)
mockups/          HTML design mockups (design process artefacts)
run_app.py        pywebview launcher - starts Django + opens native window
pdforge.spec      PyInstaller build spec
package_app.command   Double-click build script (creates dist/PDForge-YYYY-MM-DD.zip)
```

---

## Running in development

```bash
# 1. Clone
git clone https://github.com/leskarpro/pdforge.git
cd pdforge

# 2. Virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Local settings (SECRET_KEY)
echo 'SECRET_KEY = "your-dev-secret-key-here"' > local_settings.py

# 4. Database
python manage.py migrate
python manage.py seed_dummy   # optional: load sample data

# 5. Run (browser dev mode)
python manage.py runserver
# or run as native window:
python run_app.py
```

> **macOS note:** For case-insensitive Cyrillic search, install `pysqlite3`:
> `brew install sqlite && pip install pysqlite3`
> Without it the app falls back to the system SQLite (search still works, just case-sensitive).

---

## Building the macOS app

```bash
# Double-click package_app.command in Finder, or:
./package_app.command
# Output: dist/PDForge-YYYY-MM-DD.zip
```

The built `.app` is self-contained - copy to `/Applications` on any Apple Silicon Mac, right-click -> Open (Gatekeeper bypass for unsigned apps), and it runs with no additional setup.

---

## Status

Active development. Core protocol management, PDF generation, OneDrive sync, and macOS packaging are complete. Dashboard (KPI charts) and advanced reporting are planned for a future stage once real client data is collected.
