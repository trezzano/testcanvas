"""
Django management command: ``import_testcanvas``.

Imports a structured TestCanvas JSON document (see
``docs/docs/json_model_format.md``) into the relational models by delegating to
:func:`testcanvas.utilities.import_data.import_model_from_json`.

The document root may be either a single model object ``{...}`` or a **list** of
model objects ``[{...}, {...}]``; every object is imported in the same run. If an
``ApplicationMap`` with the same name already exists it is overwritten and a
warning is reported.

The JSON file is looked up inside a *data directory* (``BASE_DIR / 'data'`` by
default) so that importable payloads live in a well known place. A different
directory can be provided with ``--data-dir`` and an absolute/relative path is
accepted directly as well.

Usage examples
--------------
    # Import <BASE_DIR>/data/checkout_flow.json
    python manage.py import_testcanvas checkout_flow.json

    # Import from a custom data directory
    python manage.py import_testcanvas payload.json --data-dir /srv/imports

    # List the .json files available in the data directory
    python manage.py import_testcanvas --list

    # Validate only, without writing anything to the database
    python manage.py import_testcanvas checkout_flow.json --dry-run
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...utilities.import_data import (
    ImportValidationError,
    import_model_from_json,
)


class Command(BaseCommand):
    # Shown by ``python manage.py help import_testcanvas``.
    help = (
        "Import a structured TestCanvas JSON document (ApplicationMap -> FlowNode "
        "-> UserStory -> AcceptanceCriterion -> TestCase) from a file located in "
        "the data directory. The root may be a single model object or a list of "
        "them. Existing ApplicationMaps with the same name are overwritten. The "
        "whole import runs in a single transaction: if anything fails nothing is "
        "left in the database."
    )

    def add_arguments(self, parser):
        """Declare the CLI arguments accepted by the command."""
        parser.add_argument(
            "filename",
            nargs="?",
            help=(
                "Name of the JSON file to import (relative to the data directory) "
                "or a full path to a .json file. Optional when using --list."
            ),
        )
        parser.add_argument(
            "--data-dir",
            dest="data_dir",
            default=None,
            help=(
                "Directory that holds the JSON payloads. "
                "Defaults to <BASE_DIR>/data."
            ),
        )
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_files",
            help="List the .json files available in the data directory and exit.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help=(
                "Validate the document and report what would be imported without "
                "writing anything to the database."
            ),
        )

    # -- helpers ---------------------------------------------------------

    def _resolve_data_dir(self, data_dir: str | None) -> Path:
        """Return the data directory as a Path, defaulting to ``BASE_DIR/data``."""
        if data_dir:
            return Path(data_dir).expanduser().resolve()
        # settings.BASE_DIR is a Path (see testcanvas_project/settings.py).
        return Path(settings.BASE_DIR) / "data"

    def _resolve_file(self, filename: str, data_dir: Path) -> Path:
        """Resolve ``filename`` to an existing file.

        A bare name is looked up inside ``data_dir``; an absolute or relative
        path is honoured as-is. Raises :class:`CommandError` when the file does
        not exist so Django prints a clean error (and exits non-zero).
        """
        candidate = Path(filename).expanduser()
        # Absolute path, or an explicit relative path containing a separator:
        # trust it directly. Otherwise treat it as a name inside the data dir.
        if candidate.is_absolute() or candidate.parent != Path("."):
            resolved = candidate.resolve()
        else:
            resolved = (data_dir / candidate).resolve()

        if not resolved.is_file():
            raise CommandError(f"File not found: {resolved}")
        if resolved.suffix.lower() != ".json":
            self.stdout.write(
                self.style.WARNING(f"Warning: '{resolved.name}' does not have a .json extension.")
            )
        return resolved

    def _list_json_files(self, data_dir: Path) -> None:
        """Print every ``.json`` file found in the data directory."""
        if not data_dir.is_dir():
            raise CommandError(f"Data directory does not exist: {data_dir}")
        files = sorted(data_dir.glob("*.json"))
        if not files:
            self.stdout.write(self.style.WARNING(f"No .json files found in {data_dir}"))
            return
        self.stdout.write(f"JSON files available in {data_dir}:")
        for path in files:
            self.stdout.write(f"  - {path.name}")

    # -- entry point -----------------------------------------------------

    def handle(self, *args, **options):
        """Command entry point invoked by Django."""
        data_dir = self._resolve_data_dir(options["data_dir"])

        # --list simply reports the available payloads and returns.
        if options["list_files"]:
            self._list_json_files(data_dir)
            return

        filename = options["filename"]
        if not filename:
            raise CommandError(
                "Missing 'filename'. Provide a JSON file to import, or use --list "
                "to see the files available in the data directory."
            )

        json_path = self._resolve_file(filename, data_dir)
        self.stdout.write(f"Importing '{json_path}'...")

        try:
            # Read the file explicitly so we can surface a clean I/O error, then
            # hand the raw text to the importer (which parses + validates it).
            payload = json_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CommandError(f"Could not read file '{json_path}': {exc}")

        # --dry-run: validate only. import_model_from_json always writes inside a
        # transaction, so we open our own atomic block and roll it back.
        if options["dry_run"]:
            self._dry_run(payload)
            return

        # Real import. On any validation/DB error the importer rolls back the
        # transaction, so the database is never left in a half-imported state.
        try:
            result = import_model_from_json(payload)
        except ImportValidationError as exc:
            # Print each precise, path-annotated error, then fail the command.
            self.stderr.write(self.style.ERROR("Import failed. No data was written."))
            for message in exc.errors:
                self.stderr.write(self.style.ERROR(f"  - {message}"))
            raise CommandError(f"Import aborted with {len(exc.errors)} error(s).")

        # Success: summary + any non-blocking warnings.
        self.stdout.write(self.style.SUCCESS(result.summary()))
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f"  warning: {warning}"))

    def _dry_run(self, payload: str) -> None:
        """Validate + simulate the import inside a transaction that is rolled back."""
        from django.db import transaction

        try:
            # Force a rollback by raising a sentinel after a successful import,
            # so the validation and DB constraints are fully exercised without
            # persisting anything.
            class _Rollback(Exception):
                pass

            holder = {}
            try:
                with transaction.atomic():
                    holder["result"] = import_model_from_json(payload)
                    raise _Rollback
            except _Rollback:
                pass
        except ImportValidationError as exc:
            self.stderr.write(self.style.ERROR("Validation failed (dry-run). No data would be written."))
            for message in exc.errors:
                self.stderr.write(self.style.ERROR(f"  - {message}"))
            raise CommandError(f"Dry-run found {len(exc.errors)} error(s).")

        result = holder["result"]
        self.stdout.write(self.style.SUCCESS(f"[dry-run] Document is valid. Would import: {result.summary()}"))
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f"  warning: {warning}"))
        self.stdout.write(self.style.NOTICE("[dry-run] Transaction rolled back — nothing was saved."))

