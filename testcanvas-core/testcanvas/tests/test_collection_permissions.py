"""Tests for the collection-based read/write permission system."""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase as DjangoTestCase
from django.urls import reverse

from testcanvas.models import (
    ApplicationMap,
    ApplicationMapsCollection,
    CollectionPermission,
    FlowNode,
    UserStory,
)
from testcanvas.utilities.permissions import (
    AccessDenied,
    AccessLevel,
    access_level,
    can_read,
    can_write,
    filter_maps,
    filter_readable,
    get_access,
    require_read,
    require_write,
)
from testcanvas.views._permissions import ensure_can_read, ensure_can_write


class CollectionPermissionTestBase(DjangoTestCase):
    """Shared fixture: a small collection tree with maps and users.

    Tree::

        Root
        ├── Child            (map_child)
        │   └── Grandchild   (map_grandchild)
        Other                (map_other)
        (no collection)      (map_orphan)
    """

    def setUp(self) -> None:
        """Create the collection tree, maps and users."""
        user_model = get_user_model()
        self.superuser = user_model.objects.create_superuser("admin", "a@x.io", "pwd")
        self.reader = user_model.objects.create_user("reader", password="pwd")
        self.writer = user_model.objects.create_user("writer", password="pwd")
        self.stranger = user_model.objects.create_user("stranger", password="pwd")

        self.root = ApplicationMapsCollection.objects.create(title="Root")
        self.child = ApplicationMapsCollection.objects.create(title="Child", parent=self.root)
        self.grandchild = ApplicationMapsCollection.objects.create(title="Grandchild", parent=self.child)
        self.other = ApplicationMapsCollection.objects.create(title="Other")

        self.map_child = ApplicationMap.objects.create(name="Child map", collection=self.child)
        self.map_grandchild = ApplicationMap.objects.create(name="Grandchild map", collection=self.grandchild)
        self.map_other = ApplicationMap.objects.create(name="Other map", collection=self.other)
        self.map_orphan = ApplicationMap.objects.create(name="Orphan map")

        # reader: read on Child (cascades to Grandchild).
        CollectionPermission.objects.create(collection=self.child, user=self.reader, can_read=True)
        # writer: write on Root (cascades to the whole Root sub-tree).
        CollectionPermission.objects.create(collection=self.root, user=self.writer, can_write=True)

    @staticmethod
    def _fresh(user):
        """Return a fresh user instance (drops the per-request access cache)."""
        return get_user_model().objects.get(pk=user.pk)


class PermissionHelperTests(CollectionPermissionTestBase):
    """Unit tests of ``testcanvas.utilities.permissions``."""

    def test_superuser_is_unrestricted(self) -> None:
        """Superusers read and write everything, including ungrouped maps."""
        for m in (self.map_child, self.map_other, self.map_orphan):
            self.assertTrue(can_read(self.superuser, m))
            self.assertTrue(can_write(self.superuser, m))

    def test_read_grant_cascades_down_only(self) -> None:
        """A read grant applies to the collection and its descendants only."""
        self.assertTrue(can_read(self.reader, self.map_child))
        self.assertTrue(can_read(self.reader, self.map_grandchild))
        self.assertFalse(can_read(self.reader, self.root))
        self.assertFalse(can_read(self.reader, self.map_other))
        self.assertFalse(can_write(self.reader, self.map_child))

    def test_write_implies_read(self) -> None:
        """A write grant also grants read, cascading to the sub-tree."""
        self.assertTrue(can_write(self.writer, self.map_grandchild))
        self.assertTrue(can_read(self.writer, self.map_grandchild))
        self.assertTrue(can_write(self.writer, self.root))

    def test_ungrouped_maps_are_superuser_only(self) -> None:
        """Maps without a collection are hidden from every non-superuser."""
        self.assertFalse(can_read(self.writer, self.map_orphan))
        self.assertFalse(can_write(self.writer, self.map_orphan))

    def test_group_grant(self) -> None:
        """Grants assigned to a group apply to its members."""
        group = Group.objects.create(name="QA")
        self.stranger.groups.add(group)
        CollectionPermission.objects.create(collection=self.other, group=group, can_read=True)
        stranger = self._fresh(self.stranger)
        self.assertTrue(can_read(stranger, self.map_other))
        self.assertFalse(can_write(stranger, self.map_other))

    def test_artefacts_inherit_map_permissions(self) -> None:
        """FlowNode / UserStory follow the owning map permissions."""
        node = FlowNode.objects.create(application_map=self.map_other, local_graph_id="n1", title="N1")
        story = UserStory.objects.create(flow_node=node, code="US-1", title="Story")
        self.assertFalse(can_read(self.reader, node))
        self.assertFalse(can_read(self.reader, story))
        self.assertTrue(can_read(self.superuser, story))

    def test_filter_maps(self) -> None:
        """``filter_maps`` keeps only the readable maps."""
        names = set(filter_maps(self.reader, ApplicationMap.objects.all()).values_list("name", flat=True))
        self.assertEqual(names, {"Child map", "Grandchild map"})

    def test_access_is_cached_per_user_instance(self) -> None:
        """Access sets are computed once per user instance (i.e. per request)."""
        user = self._fresh(self.reader)
        get_access(user)
        with self.assertNumQueries(0):
            get_access(user)

    def test_access_level_three_states(self) -> None:
        """access_level distinguishes NONE / READ / WRITE without HTTP coupling."""
        self.assertEqual(access_level(self.reader, self.map_child), AccessLevel.READ)
        self.assertEqual(access_level(self.reader, self.map_other), AccessLevel.NONE)
        self.assertEqual(access_level(self.writer, self.map_grandchild), AccessLevel.WRITE)

    def test_require_read_write_raise_access_denied_with_level(self) -> None:
        """require_read / require_write never raise HTTP exceptions."""
        with self.assertRaises(AccessDenied) as ctx:
            require_read(self.reader, self.map_other)
        self.assertEqual(ctx.exception.level, AccessLevel.NONE)

        with self.assertRaises(AccessDenied) as ctx:
            require_write(self.reader, self.map_child)
        self.assertEqual(ctx.exception.level, AccessLevel.READ)

        # No exception when access is sufficient.
        require_read(self.reader, self.map_child)
        require_write(self.writer, self.map_grandchild)

    def test_filter_readable_generic_across_chain(self) -> None:
        """filter_readable works on any registered model, not just maps."""
        node = FlowNode.objects.create(application_map=self.map_child, local_graph_id="n1", title="N1")
        story = UserStory.objects.create(flow_node=node, code="US-1", title="Story")
        visible = filter_readable(self.reader, UserStory.objects.all())
        self.assertIn(story, visible)

        other_node = FlowNode.objects.create(application_map=self.map_other, local_graph_id="n2", title="N2")
        UserStory.objects.create(flow_node=other_node, code="US-2", title="Other story")
        visible_codes = set(filter_readable(self.reader, UserStory.objects.all()).values_list("code", flat=True))
        self.assertEqual(visible_codes, {"US-1"})

    def test_http_adapter_maps_access_denied_to_404_and_403(self) -> None:
        """The views._permissions adapter is the only place turning AccessDenied into HTTP."""
        from django.core.exceptions import PermissionDenied
        from django.http import Http404

        with self.assertRaises(Http404):
            ensure_can_read(self.reader, self.map_other)
        with self.assertRaises(Http404):
            ensure_can_write(self.reader, self.map_other)
        with self.assertRaises(PermissionDenied):
            ensure_can_write(self.reader, self.map_child)
        # No exception when access is sufficient.
        ensure_can_read(self.reader, self.map_child)
        ensure_can_write(self.writer, self.map_grandchild)


class PermissionViewTests(CollectionPermissionTestBase):
    """Integration tests of the permission checks in the views."""

    def test_map_list_is_filtered(self) -> None:
        """The flow list shows only the readable maps."""
        self.client.force_login(self.reader)
        response = self.client.get(reverse("testcanvas:map_list"))
        names = {m.name for m in response.context["maps"]}
        self.assertEqual(names, {"Child map", "Grandchild map"})

    def test_superuser_sees_everything(self) -> None:
        """Superusers see every map, ungrouped ones included."""
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("testcanvas:map_list"))
        self.assertEqual(len(response.context["maps"]), 4)

    def test_editor_unreadable_map_is_404(self) -> None:
        """Opening an unreadable map answers 404 (no disclosure)."""
        self.client.force_login(self.reader)
        response = self.client.get(reverse("testcanvas:map_editor", args=[self.map_other.pk]))
        self.assertEqual(response.status_code, 404)

    def test_editor_read_only_flag(self) -> None:
        """A reader opens the editor in read-only mode."""
        self.client.force_login(self.reader)
        response = self.client.get(reverse("testcanvas:map_editor", args=[self.map_child.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_write"])

    def test_map_save_requires_write(self) -> None:
        """A reader cannot save the graph."""
        self.client.force_login(self.reader)
        response = self.client.post(
            reverse("testcanvas:map_save", args=[self.map_child.pk]),
            data=json.dumps({"elements": {"nodes": [], "edges": []}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_map_save_cannot_move_to_unwritable_collection(self) -> None:
        """A writer cannot move a map into a collection it cannot write."""
        self.client.force_login(self.writer)
        response = self.client.post(
            reverse("testcanvas:map_save", args=[self.map_child.pk]),
            data=json.dumps({"elements": {"nodes": [], "edges": []}, "collection": self.other.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.map_child.refresh_from_db()
        self.assertEqual(self.map_child.collection_id, self.child.pk)

    def test_map_save_cannot_detach_collection(self) -> None:
        """A non-superuser cannot move a map to the default (no) collection."""
        self.client.force_login(self.writer)
        response = self.client.post(
            reverse("testcanvas:map_save", args=[self.map_child.pk]),
            data=json.dumps({"elements": {"nodes": [], "edges": []}, "collection": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_map_save_by_writer(self) -> None:
        """A writer can save a map of a writable collection."""
        self.client.force_login(self.writer)
        response = self.client.post(
            reverse("testcanvas:map_save", args=[self.map_grandchild.pk]),
            data=json.dumps({"elements": {"nodes": [], "edges": []}, "name": "Renamed"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.map_grandchild.refresh_from_db()
        self.assertEqual(self.map_grandchild.name, "Renamed")

    def test_map_create_requires_writable_collection(self) -> None:
        """Non-superusers must create maps inside a writable collection."""
        self.client.force_login(self.writer)
        self.client.post(reverse("testcanvas:map_create"), {"name": "No coll"})
        self.assertFalse(ApplicationMap.objects.filter(name="No coll").exists())
        self.client.post(reverse("testcanvas:map_create"), {"name": "Other", "collection": self.other.pk})
        self.assertFalse(ApplicationMap.objects.filter(name="Other").exists())
        self.client.post(reverse("testcanvas:map_create"), {"name": "Ok", "collection": self.child.pk})
        self.assertTrue(ApplicationMap.objects.filter(name="Ok", collection=self.child).exists())

    def test_uid_resolver_does_not_bypass(self) -> None:
        """Resolving the UID of an unreadable map answers 404."""
        self.client.force_login(self.reader)
        response = self.client.get(reverse("testcanvas:dynamic_show_by_uid", args=[self.map_other.uid]))
        self.assertEqual(response.status_code, 404)

    def test_user_story_create_requires_write(self) -> None:
        """A reader can view the stories list but cannot create a story."""
        node = FlowNode.objects.create(application_map=self.map_child, local_graph_id="n1", title="N1")
        self.client.force_login(self.reader)
        url = reverse("testcanvas:user_story_manage", args=[node.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"code": "US-1", "title": "T", "priority": "MEDIUM"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserStory.objects.filter(flow_node=node).exists())

    def test_collection_tree_prunes_unreadable_branches(self) -> None:
        """The tree hides unreadable branches and keeps ancestors as containers."""
        self.client.force_login(self.reader)
        response = self.client.get(reverse("testcanvas:collection_tree"))
        tree = response.context["tree"]
        self.assertEqual([node["title"] for node in tree], ["Root"])
        self.assertFalse(tree[0]["is_accessible"])
        self.assertTrue(tree[0]["children"][0]["is_accessible"])

    def test_collection_create_root_forbidden_for_non_superuser(self) -> None:
        """Non-superusers cannot create root collections."""
        self.client.force_login(self.writer)
        self.client.post(reverse("testcanvas:collection_create"), {
            "title": "New root", "background_color": "#ef4444", "parent": "",
        })
        self.assertFalse(ApplicationMapsCollection.objects.filter(title="New root").exists())
        self.client.post(reverse("testcanvas:collection_create"), {
            "title": "New child", "background_color": "#ef4444", "parent": self.child.pk,
        })
        self.assertTrue(ApplicationMapsCollection.objects.filter(title="New child", parent=self.child).exists())

    def test_collection_delete_blocked_when_it_contains_maps(self) -> None:
        """Non-superusers cannot delete collections that still contain flows."""
        self.client.force_login(self.writer)
        self.client.post(reverse("testcanvas:collection_delete", args=[self.child.pk]))
        self.assertTrue(ApplicationMapsCollection.objects.filter(pk=self.child.pk).exists())

    def test_field_settings_superuser_only(self) -> None:
        """The global optional-field settings page is reserved to superusers."""
        url = reverse("testcanvas:project_field_settings")
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_collection_move_to_unwritable_parent_forbidden(self) -> None:
        """Moving under a non-writable collection is rejected."""
        self.client.force_login(self.writer)
        self.client.post(
            reverse("testcanvas:collection_move", args=[self.grandchild.pk]),
            {"parent_id": self.other.pk},
        )
        self.grandchild.refresh_from_db()
        self.assertEqual(self.grandchild.parent_id, self.child.pk)

