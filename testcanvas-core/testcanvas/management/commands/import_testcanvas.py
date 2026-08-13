"""Django management command: ``import_testcanvas`` (placeholder).
The structured-JSON importer was removed while Test Case management moved to the
``testcanvas_test_execution`` plugin. This command is kept as a thin placeholder
so tooling and docs keep resolving; it delegates to
:func:`testcanvas.utilities.import_data.import_model_from_json`, which currently
raises :class:`NotImplementedError` until the new import contract is defined.
"""
from __future__ import annotations
from django.core.management.base import BaseCommand, CommandError
from ...utilities.import_data import import_model_from_json
class Command(BaseCommand):
    # Shown by ``python manage.py help import_testcanvas``.
    help = (
        "Import a structured TestCanvas JSON document. Placeholder: the importer "
        "is not implemented yet (Test Cases moved to the "
        "testcanvas_test_execution plugin)."
    )
    def add_arguments(self, parser):
        """Declare the CLI arguments accepted by the command."""
        parser.add_argument(
            "filename",
            nargs="?",
            help="Name/path of the JSON file to import (currently unused).",
        )
    def handle(self, *args, **options):
        """Command entry point invoked by Django.
        Raises:
            CommandError: Always, because the importer is not implemented yet.
        """
        try:
            import_model_from_json("")
        except NotImplementedError as exc:
            raise CommandError(
                f"import_testcanvas is not implemented yet: {exc}."
            )
