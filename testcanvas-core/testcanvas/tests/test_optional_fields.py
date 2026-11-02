"""Tests guarding the optional-fields catalogue (Option A)."""

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from testcanvas.models import FieldVisibilityPreference
from testcanvas.utilities.optional_fields import OPTIONAL_FIELDS, get_optional_fields_status


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


class OptionalFieldsStatusTest(TestCase):
    """Check the catalogue report returned by ``get_optional_fields_status``."""

    def test_report_mirrors_catalogue_order(self):
        """Every catalogued field is reported, in catalogue order."""
        status = get_optional_fields_status()

        self.assertEqual(list(status), list(OPTIONAL_FIELDS))
        for model_name, specs in OPTIONAL_FIELDS.items():
            self.assertEqual(
                [(item["name"], item["label"]) for item in status[model_name]],
                [(spec.name, spec.label) for spec in specs],
            )

    def test_enabled_flag_follows_preferences(self):
        """Enabled rows report True; disabled or missing rows report False."""
        FieldVisibilityPreference.objects.create(
            target_model="UserStory", field_name="story_points", is_visible=True,
        )
        FieldVisibilityPreference.objects.create(
            target_model="UserStory", field_name="risk_level", is_visible=False,
        )

        enabled = {
            item["name"]: item["enabled"]
            for item in get_optional_fields_status()["UserStory"]
        }

        self.assertTrue(enabled["story_points"])   # explicit True row
        self.assertFalse(enabled["risk_level"])    # explicit False row
        self.assertFalse(enabled["status"])        # no row at all


