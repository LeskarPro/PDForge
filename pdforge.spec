# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for PDForge (Stage 6c-2).
#
# Build with:
#   pyinstaller --noconfirm pdforge.spec
#
# Output: dist/PDForge.app
#
import os

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# WeasyPrint's cffi backend dlopens these at runtime via ctypes (not via
# normal linking), so PyInstaller's dependency scanner won't discover them
# on its own — list the roots explicitly. PyInstaller then also pulls in
# their transitive dependencies (glib, cairo, freetype, etc.) and rewrites
# all the internal load paths so the result is self-contained — the
# target Mac needs no Homebrew at all.
_homebrew_lib = "/opt/homebrew/lib" if os.path.exists("/opt/homebrew/lib") else "/usr/local/lib"
_weasyprint_dylibs = [
    "libgobject-2.0.0.dylib",
    "libpango-1.0.dylib",
    "libharfbuzz.0.dylib",
    "libharfbuzz-subset.0.dylib",
    "libfontconfig.1.dylib",
    "libpangoft2-1.0.dylib",
]
binaries = [
    (os.path.join(_homebrew_lib, name), ".")
    for name in _weasyprint_dylibs
    if os.path.exists(os.path.join(_homebrew_lib, name))
]

hiddenimports = (
    collect_submodules("core")
    + collect_submodules("weasyprint")
    + collect_submodules("pyphen")
    + collect_submodules("tinycss2")
    + collect_submodules("tinyhtml5")
    + collect_submodules("cssselect2")
    + [
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "django.contrib.humanize",
        "django.template.loaders.app_directories",
    ]
)

# Bundled, read-only resources the app needs at runtime:
#  - templates/   -> TEMPLATES["DIRS"] (BASE_DIR/templates, BASE_DIR == sys._MEIPASS when frozen)
#  - seed/         -> first-run seed db.sqlite3 (copied into Application Support)
#  - core/static/  -> app static assets
datas = [
    ("templates", "templates"),
    ("seed", "seed"),
    ("core/static", "core/static"),
    ("fontconfig", "fontconfig"),
]

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# Defensive: the Analysis step picks up the project's *dev* db.sqlite3 (from
# the project root, via pathex=["."]) as a stray top-level data file. That
# file can contain Kiril's real business data and must never end up in the
# shipped .app — strip it, whatever hook is adding it.
a.datas = [d for d in a.datas if d[0] != "db.sqlite3"]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PDForge",
)

app = BUNDLE(
    coll,
    name="PDForge.app",
    icon="design/icon/pdforge_icon.icns",
    bundle_identifier="com.kiril.pdforge",
    info_plist={
        "NSHighResolutionCapable": True,
    },
)
