from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TestcanvasConfig(AppConfig):
    """Configuration for the core TestCanvas app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'testcanvas'
    label = 'testcanvas'


