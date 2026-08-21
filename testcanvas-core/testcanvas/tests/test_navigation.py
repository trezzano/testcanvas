"""Tests for the shared plugin navbar context processor."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from testcanvas.context_processors import plugin_navbar


class PluginNavbarContextProcessorTests(SimpleTestCase):
    """Validate ordering and visibility rules for plugin navbar links."""

    def setUp(self) -> None:
        """Create common test helpers."""
        self.factory = RequestFactory()

    def _request(self, namespace: str = ""):
        """Build a request with an authenticated test user.

        Args:
            namespace: Namespace to expose as current route namespace.

        Returns:
            A request object suitable for the context processor.
        """
        request = self.factory.get("/")
        request.user = cast(
            Any,
            SimpleNamespace(
            is_authenticated=True,
            has_perm=lambda permission: permission == "allowed.permission",
            ),
        )
        request.resolver_match = cast(Any, SimpleNamespace(namespace=namespace))
        return request

    @patch("testcanvas.context_processors.apps.get_app_configs")
    def test_returns_empty_links_for_anonymous_user(self, mocked_configs) -> None:
        """Skip navbar generation for anonymous requests."""
        request = self.factory.get("/")
        request.user = cast(
            Any,
            SimpleNamespace(is_authenticated=False, has_perm=lambda _: False),
        )

        context = plugin_navbar(request)

        self.assertEqual(context["nav_links"], [])
        mocked_configs.assert_not_called()

    @override_settings(NAVBAR_APP_ORDER={"alpha": 1, "beta": 1, "testcanvas": 0})
    @patch("testcanvas.context_processors.reverse")
    @patch("testcanvas.context_processors.apps.get_app_configs")
    def test_configured_order_wins_and_conflicts_fall_back_to_alpha(
        self,
        mocked_configs,
        mocked_reverse,
    ) -> None:
        """Apply settings order first, then alphabetical AppConfig.label tie-break."""
        mocked_reverse.side_effect = lambda url_name, args=None, kwargs=None: f"/{url_name}/"

        mocked_configs.return_value = [
            SimpleNamespace(
                label="beta",
                name="example.beta",
                nav_items=[{"label": "Beta Link", "url_name": "beta:home"}],
            ),
            SimpleNamespace(
                label="gamma",
                name="example.gamma",
                nav_items=[{"label": "Gamma Link", "url_name": "gamma:home"}],
            ),
            SimpleNamespace(
                label="alpha",
                name="example.alpha",
                nav_items=[{"label": "Alpha Link", "url_name": "alpha:home"}],
            ),
        ]

        context = plugin_navbar(self._request(namespace="alpha"))

        self.assertEqual(
            [item["label"] for item in context["nav_links"]],
            ["Alpha Link", "Beta Link", "Gamma Link"],
        )
        self.assertTrue(context["nav_links"][0]["active"])

    @override_settings(NAVBAR_APP_ORDER={})
    @patch("testcanvas.context_processors.reverse")
    @patch("testcanvas.context_processors.apps.get_app_configs")
    def test_no_defined_order_uses_alphabetical_app_label(
        self,
        mocked_configs,
        mocked_reverse,
    ) -> None:
        """Sort alphabetically by app label when no app order is configured."""
        mocked_reverse.side_effect = lambda url_name, args=None, kwargs=None: f"/{url_name}/"

        mocked_configs.return_value = [
            SimpleNamespace(
                label="zeta",
                name="example.zeta",
                nav_items=[{"label": "Zeta", "url_name": "zeta:home"}],
            ),
            SimpleNamespace(
                label="eta",
                name="example.eta",
                nav_items=[{"label": "Eta", "url_name": "eta:home"}],
            ),
        ]

        context = plugin_navbar(self._request())

        self.assertEqual([item["label"] for item in context["nav_links"]], ["Eta", "Zeta"])

    @patch("testcanvas.context_processors.reverse")
    @patch("testcanvas.context_processors.apps.get_app_configs")
    def test_permission_filter_and_dynamic_getter_are_supported(
        self,
        mocked_configs,
        mocked_reverse,
    ) -> None:
        """Use get_nav_items(request) and hide links without the required permission."""
        mocked_reverse.side_effect = lambda url_name, args=None, kwargs=None: f"/{url_name}/"

        config = SimpleNamespace(label="delta", name="example.delta", nav_items=[{"label": "Ignored"}])

        def get_nav_items(_request):
            return [
                {
                    "label": "Visible",
                    "url_name": "delta:visible",
                    "permission": "allowed.permission",
                },
                {
                    "label": "Hidden",
                    "url_name": "delta:hidden",
                    "permission": "denied.permission",
                },
            ]

        config.get_nav_items = get_nav_items
        mocked_configs.return_value = [config]

        context = plugin_navbar(self._request())

        self.assertEqual([item["label"] for item in context["nav_links"]], ["Visible"])

    @patch("testcanvas.context_processors.apps.get_app_configs")
    @patch("testcanvas.context_processors.reverse")
    def test_unresolvable_urls_are_safely_skipped(self, mocked_reverse, mocked_configs) -> None:
        """Do not break navbar rendering when one url_name cannot be reversed."""
        from django.urls import NoReverseMatch

        def reverse_side_effect(url_name: str, args=None, kwargs=None) -> str:
            if url_name == "broken:missing":
                raise NoReverseMatch("broken")
            return f"/{url_name}/"

        mocked_reverse.side_effect = reverse_side_effect
        mocked_configs.return_value = [
            SimpleNamespace(
                label="omega",
                name="example.omega",
                nav_items=[
                    {"label": "Broken", "url_name": "broken:missing"},
                    {"label": "Working", "url_name": "omega:home"},
                ],
            )
        ]

        context = plugin_navbar(self._request())

        self.assertEqual([item["label"] for item in context["nav_links"]], ["Working"])

