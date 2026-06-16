from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.db.backends.signals import connection_created

        def _register_unicode_functions(sender, connection, **kwargs):
            """Override SQLite UPPER/LOWER with Python-backed versions so that
            Django's icontains works correctly for Cyrillic and all Unicode.
            Django generates: UPPER(col) LIKE UPPER('%query%')
            Built-in SQLite UPPER only handles ASCII — this fixes that.
            """
            if connection.vendor == 'sqlite':
                db = connection.connection
                db.create_function('UPPER', 1,
                    lambda x: x.upper() if isinstance(x, str) else x)
                db.create_function('LOWER', 1,
                    lambda x: x.lower() if isinstance(x, str) else x)

        connection_created.connect(_register_unicode_functions)

        # ── Stage 6a: bump AppSettings.data_version on any data change ─────
        # Used by the OneDrive/backup sync to detect "local data changed
        # since the last sync" without hashing the whole DB file.
        from django.db.models.signals import post_save, post_delete
        from django.utils import timezone

        def _bump_data_version(sender, **kwargs):
            from .models import AppSettings
            AppSettings.objects.filter(pk=1).update(data_version=timezone.now())

        for model in self.get_models():
            if model.__name__ == 'AppSettings':
                continue
            post_save.connect(
                _bump_data_version, sender=model, weak=False,
                dispatch_uid=f'sync_bump_dv_save_{model.__name__}',
            )
            post_delete.connect(
                _bump_data_version, sender=model, weak=False,
                dispatch_uid=f'sync_bump_dv_delete_{model.__name__}',
            )

        # ── Stage 6a: periodic background backup push ──────────────────
        # Only start the thread for processes that actually serve the app
        # (not for migrate/shell/management commands), and avoid starting
        # it twice when runserver's autoreloader spawns two processes.
        import os
        import sys
        from django.conf import settings

        argv = sys.argv
        non_serving_commands = {
            'migrate', 'makemigrations', 'shell', 'shell_plus', 'test',
            'collectstatic', 'createsuperuser', 'dbshell', 'check',
            'showmigrations', 'sqlmigrate', 'dumpdata', 'loaddata',
            'seed_dummy', 'seed_one_time',
        }
        command = argv[1] if len(argv) > 1 else None

        if settings.FROZEN:
            # Packaged Mac app: run_app.py is the only entry point and it
            # always serves. sys.argv here is whatever macOS/PyInstaller's
            # bootloader passed (often just the exe path, sometimes with an
            # LSOpenFileArgs flag) — not a management command — so the argv
            # sniffing below doesn't apply.
            should_start = True
        elif command == 'runserver':
            should_start = (os.environ.get('RUN_MAIN') == 'true') or ('--noreload' in argv)
        elif command not in non_serving_commands and command is not None:
            # e.g. a custom management command used by the packaged Mac app
            should_start = True
        else:
            should_start = False

        if should_start:
            from . import sync_service
            sync_service.start_periodic_sync()
