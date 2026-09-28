"""Tests guarding the optional-fields catalogue (Option A)."""

from django.apps import apps
from django.test import SimpleTestCase

from testcanvas.utilities.optional_fields import OPTIONAL_FIELDS


class OptionalFieldsCatalogueTest(SimpleTestCase):
    """Ensure the explicit catalogue stays in sync with the models."""

    def test_declared_optional_fields_exist_on_models(self):
        """Every catalogued field name must exist on its target model.

        This prevents the catalogue and the schema from drifting apart: if a
        field is renamed or removed without updating the catalogue (or vice
        versa), this test fails immediately instead of breaking the settings
        page at runtime.
        """
        for model_name, specs in OPTIONAL_FIELDS.items():
            model = apps.get_model("testcanvas", model_name)
            field_names = {field.name for field in model._meta.get_fields()}
            for spec in specs:
                self.assertIn(
                    spec.name,
                    field_names,
                    msg=f"{model_name}.{spec.name} is catalogued but missing on the model",
                )

