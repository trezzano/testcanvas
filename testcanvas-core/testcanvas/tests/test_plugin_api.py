"""Tests of the plugin-friendly public API (UID utilities, resolution, services, serialization)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError

from testcanvas import api
from testcanvas.models import (
    AcceptanceCriterion,
    ApplicationMap,
    CollectionPermission,
    FlowNode,
    TestCase,
    UserStory,
)
from testcanvas.services import (
    MapInUseAsSubflow,
    SubflowCannotOwnUserStories,
    create_acceptance_criteria,
    create_user_stories,
    delete_artefact,
    deletion_preview,
    duplicate_by_uid,
    update_application_map,
    update_artefact,
)
from testcanvas.tests.test_collection_permissions import CollectionPermissionTestBase
from testcanvas.utilities.other_support import UID_MODELS, find_model_object_by_uid
from testcanvas.utilities.permissions import (
    AccessDenied,
    AccessLevel,
    ObjectNotFound,
    get_collection_for_user,
    get_object_by_uid_for_user,
)
from testcanvas.utilities.serialization import serialize_flow_overview

# Two connected nodes: n1 (PURE, owns the ISTQB chain) and n2.
_GRAPH = {
    "elements": {
        "nodes": [
            {"data": {"id": "n1", "name": "N1", "value": "n1"}},
            {"data": {"id": "n2", "name": "N2", "value": "n2"}},
        ],
        "edges": [{"data": {"id": "e1", "source": "n1", "target": "n2"}}],
    },
}


class PluginApiTestBase(CollectionPermissionTestBase):
    """Extend the permission fixture with a full ISTQB chain in ``map_child``.

    Adds an inactive user (with a write grant on Root, which must be ignored)
    and the anonymous user, so every user type can be exercised.
    """

    def setUp(self) -> None:
        """Create the chain map -> node -> story -> criterion -> test case."""
        super().setUp()
        user_model = get_user_model()
        self.inactive = user_model.objects.create_user("inactive", password="pwd")
        CollectionPermission.objects.create(collection=self.root, user=self.inactive, can_write=True)
        self.inactive.is_active = False
        self.inactive.save()
        self.anonymous = AnonymousUser()

        self.map_child.graph_data = _GRAPH
        self.map_child.save()  # sync creates FlowNode n1 and n2
        self.node = self.map_child.relational_nodes.get(local_graph_id="n1")
        self.node2 = self.map_child.relational_nodes.get(local_graph_id="n2")
        self.story = UserStory.objects.create(flow_node=self.node, code="US-1", title="Story")
        self.criterion = AcceptanceCriterion.objects.create(
            user_story=self.story, code="AC-1", description="Criterion",
        )
        self.test_case = TestCase.objects.create(acceptance_criterion=self.criterion, code="TC-1")
        self.chain = [self.map_child, self.node, self.story, self.criterion, self.test_case]


# --------------------------------------------------------------------------- #
# UID utilities
# --------------------------------------------------------------------------- #


class UidLookupTests(PluginApiTestBase):
    """Tests of the shared ``uid`` field and of ``find_model_object_by_uid``."""

    def test_every_uid_model_has_a_uid_field(self) -> None:
        """Every artefact stores its UID in the common ``uid`` field."""
        for model in UID_MODELS:
            self.assertEqual(model._meta.get_field("uid").name, "uid")
        for obj in self.chain:
            self.assertTrue(obj.uid)

    def test_each_artefact_type_resolves_to_its_model(self) -> None:
        """Every artefact UID resolves to the artefact itself."""
        for obj in self.chain:
            found = find_model_object_by_uid(obj.uid)
            self.assertIsInstance(found, type(obj))
            self.assertEqual(found.pk, obj.pk)

    def test_lookup_uses_at_most_five_queries(self) -> None:
        """One indexed query per table: 5 for the deepest, 1 for a map."""
        with self.assertNumQueries(5):
            find_model_object_by_uid(self.test_case.uid)
        with self.assertNumQueries(1):
            find_model_object_by_uid(self.map_child.uid)

    def test_invalid_input_returns_none(self) -> None:
        """Unknown, empty, blank and non-string input give ``None``."""
        for value in ("unknown-uid", "", "   ", None, 123, ["x"]):
            self.assertIsNone(find_model_object_by_uid(value))

    def test_surrounding_whitespace_is_ignored(self) -> None:
        """A UID padded with whitespace still resolves."""
        self.assertEqual(find_model_object_by_uid(f"  {self.story.uid} ").pk, self.story.pk)

    def test_first_match_wins_in_fixed_order(self) -> None:
        """Documents the cross-table uniqueness assumption: first table wins."""
        FlowNode.objects.filter(pk=self.node.pk).update(uid=self.map_child.uid)
        self.assertIsInstance(find_model_object_by_uid(self.map_child.uid), ApplicationMap)

        TestCase.objects.filter(pk=self.test_case.pk).update(uid=self.story.uid)
        self.assertIsInstance(find_model_object_by_uid(self.story.uid), UserStory)


# --------------------------------------------------------------------------- #
# Permission-aware resolution
# --------------------------------------------------------------------------- #


class ObjectResolutionTests(PluginApiTestBase):
    """Tests of ``get_object_by_uid_for_user``."""

    def test_readable_users_resolve(self) -> None:
        """Superuser, writer and reader can read every artefact of map_child."""
        for user in (self.superuser, self.writer, self.reader):
            for obj in self.chain:
                found = get_object_by_uid_for_user(user, obj.uid)
                self.assertEqual(found.pk, obj.pk)

    def test_unknown_and_unreadable_give_identical_errors(self) -> None:
        """Unknown and unreadable UIDs are indistinguishable for every user type."""
        hidden = self.map_other.uid
        for user in (self.reader, self.writer, self.stranger, self.inactive, self.anonymous):
            with self.assertRaises(ObjectNotFound) as unknown:
                get_object_by_uid_for_user(user, "does-not-exist")
            with self.assertRaises(ObjectNotFound) as unreadable:
                get_object_by_uid_for_user(user, hidden)
            self.assertEqual(str(unknown.exception), str(unreadable.exception))
            self.assertIs(type(unknown.exception), type(unreadable.exception))

    def test_users_without_grant_cannot_read(self) -> None:
        """Stranger, inactive and anonymous users see nothing in map_child."""
        for user in (self.stranger, self.inactive, self.anonymous):
            with self.assertRaises(ObjectNotFound):
                get_object_by_uid_for_user(user, self.story.uid)

    def test_superuser_reads_ungrouped_maps(self) -> None:
        """Only superusers resolve maps of the default collection."""
        self.assertEqual(get_object_by_uid_for_user(self.superuser, self.map_orphan.uid), self.map_orphan)
        with self.assertRaises(ObjectNotFound):
            get_object_by_uid_for_user(self.writer, self.map_orphan.uid)

    def test_model_mismatch_is_not_found(self) -> None:
        """A wrong ``model`` filter is reported as not found."""
        with self.assertRaises(ObjectNotFound):
            get_object_by_uid_for_user(self.superuser, self.story.uid, model=TestCase)
        found = get_object_by_uid_for_user(
            self.superuser, self.story.uid, model=(TestCase, UserStory),
        )
        self.assertEqual(found.pk, self.story.pk)

    def test_read_only_user_requiring_write(self) -> None:
        """A reader asking for WRITE gets ``AccessDenied(level=READ)``."""
        with self.assertRaises(AccessDenied) as ctx:
            get_object_by_uid_for_user(self.reader, self.criterion.uid, required=AccessLevel.WRITE)
        self.assertEqual(ctx.exception.level, AccessLevel.READ)
        found = get_object_by_uid_for_user(self.writer, self.criterion.uid, required=AccessLevel.WRITE)
        self.assertEqual(found.pk, self.criterion.pk)


class CollectionResolutionTests(PluginApiTestBase):
    """Tests of ``get_collection_for_user``."""

    def test_default_collection(self) -> None:
        """``None`` is the default collection: superusers only."""
        self.assertIsNone(get_collection_for_user(self.superuser, None, AccessLevel.WRITE))
        with self.assertRaises(ObjectNotFound):
            get_collection_for_user(self.writer, None)

    def test_missing_invalid_and_unreadable_ids(self) -> None:
        """Missing, invalid and unreadable ids give identical errors."""
        messages = set()
        for value in (999999, "abc", True, self.other.pk):
            with self.assertRaises(ObjectNotFound) as ctx:
                get_collection_for_user(self.reader, value)
            messages.add(str(ctx.exception))
        self.assertEqual(len(messages), 1)

    def test_read_only_collection(self) -> None:
        """Readable but not writable collections raise ``AccessDenied(READ)``."""
        self.assertEqual(get_collection_for_user(self.reader, self.child.pk), self.child)
        self.assertEqual(get_collection_for_user(self.reader, str(self.child.pk)), self.child)
        with self.assertRaises(AccessDenied) as ctx:
            get_collection_for_user(self.reader, self.child.pk, AccessLevel.WRITE)
        self.assertEqual(ctx.exception.level, AccessLevel.READ)


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #


class ServiceTests(PluginApiTestBase):
    """Tests of ``testcanvas.services``."""

    def test_permission_is_checked_on_parent(self) -> None:
        """Creating a child needs write access on the parent."""
        with self.assertRaises(AccessDenied):
            create_user_stories(self.reader, self.node, [{"code": "US-2", "title": "T"}])
        with self.assertRaises(AccessDenied):
            create_acceptance_criteria(self.stranger, self.story, [{"code": "AC-9", "description": "d"}])
        created = create_user_stories(self.writer, self.node, [{"code": "US-2", "title": "T"}])
        self.assertEqual(created[0].flow_node_id, self.node.pk)

    def test_subflow_rule(self) -> None:
        """A SUBFLOW node cannot own User Stories."""
        FlowNode.objects.filter(pk=self.node2.pk).update(node_type=FlowNode.SUBFLOW, sub_flow=self.map_grandchild)
        self.node2.refresh_from_db()
        with self.assertRaises(SubflowCannotOwnUserStories):
            create_user_stories(self.writer, self.node2, [{"code": "US-3", "title": "T"}])
        self.assertFalse(self.node2.user_stories.exists())

    def test_bulk_create_is_atomic(self) -> None:
        """One invalid item means nothing is persisted."""
        with self.assertRaises(ValidationError) as ctx:
            create_acceptance_criteria(self.writer, self.story, [
                {"code": "AC-2", "description": "ok"},
                {"code": "AC-2", "description": "duplicate code"},
            ])
        self.assertEqual(ctx.exception.item_index, 1)
        with self.assertRaises(ValidationError):
            create_acceptance_criteria(self.writer, self.story, [
                {"code": "AC-3", "description": "ok"},
                {"bogus_field": 1},
            ])
        self.assertEqual(list(self.story.criteria.values_list("code", flat=True)), ["AC-1"])

    def test_moving_a_map_requires_write_on_both_collections(self) -> None:
        """The map and the target collection must both be writable."""
        with self.assertRaises(AccessDenied):
            update_application_map(self.writer, self.map_child, collection=self.other)
        with self.assertRaises(AccessDenied):
            update_application_map(self.reader, self.map_child, collection=self.grandchild)
        CollectionPermission.objects.create(collection=self.other, user=self.writer, can_write=True)
        writer = self._fresh(self.writer)
        update_application_map(writer, self.map_child, collection=self.other)
        self.map_child.refresh_from_db()
        self.assertEqual(self.map_child.collection_id, self.other.pk)

    def test_deletion_preview_matches_actual_deletion(self) -> None:
        """Everything listed by the preview is gone after the deletion."""
        preview = deletion_preview(self.map_child)
        self.assertEqual(preview["uid"], self.map_child.uid)
        self.assertEqual(preview["total"], 1 + 2 + 1 + 1 + 1)
        result = delete_artefact(self.writer, self.map_child)
        self.assertEqual(result, preview)
        for model_name, uids in preview["descendants"].items():
            model = {m.__name__: m for m in (FlowNode, UserStory, AcceptanceCriterion, TestCase)}[model_name]
            self.assertFalse(model.objects.filter(**{"uid__in": uids}).exists())
        self.assertFalse(ApplicationMap.objects.filter(pk=self.map_child.pk).exists())

    def test_deleting_a_flow_node_keeps_graph_in_sync(self) -> None:
        """A deleted node disappears from graph_data with its dangling edges."""
        preview = delete_artefact(self.writer, self.node)
        self.assertEqual(preview["descendants"]["UserStory"], [self.story.uid])
        self.map_child.refresh_from_db()
        elements = self.map_child.graph_data["elements"]
        self.assertEqual([n["data"]["id"] for n in elements["nodes"]], ["n2"])
        self.assertEqual(elements["edges"], [])
        self.assertFalse(FlowNode.objects.filter(pk=self.node.pk).exists())
        self.assertFalse(UserStory.objects.filter(pk=self.story.pk).exists())

    def test_map_used_as_subflow_cannot_be_deleted(self) -> None:
        """Deleting a referenced map raises and deletes nothing."""
        FlowNode.objects.create(
            application_map=self.map_grandchild, local_graph_id="x", title="X",
            node_type=FlowNode.SUBFLOW, sub_flow=self.map_child,
        )
        with self.assertRaises(MapInUseAsSubflow):
            delete_artefact(self.superuser, self.map_child)
        self.assertTrue(ApplicationMap.objects.filter(pk=self.map_child.pk).exists())

    def test_update_artefact(self) -> None:
        """Partial updates honour permissions and the allowed fields."""
        with self.assertRaises(AccessDenied):
            update_artefact(self.reader, self.story, {"title": "New"}, {"title"})
        with self.assertRaises(ValidationError):
            update_artefact(self.writer, self.story, {"code": "X"}, {"title"})
        with self.assertRaises(ValidationError):
            update_artefact(self.writer, self.story, {"uid": "X"}, {"uid"})
        fields = update_artefact(self.writer, self.story, {"title": "New"}, {"title"})
        self.assertEqual(fields, ["title"])
        self.story.refresh_from_db()
        self.assertEqual(self.story.title, "New")

    def test_duplicate_by_uid_enforces_write_when_user_given(self) -> None:
        """Passing a user enforces write access on the original."""
        with self.assertRaises(AccessDenied):
            duplicate_by_uid(self.story.uid, user=self.reader)
        with self.assertRaises(ObjectNotFound):
            duplicate_by_uid(self.story.uid, user=self.stranger)
        clone = duplicate_by_uid(self.story.uid, user=self.writer)
        self.assertNotEqual(clone.uid, self.story.uid)
        # Backward compatibility: no user, no check.
        self.assertIsNotNone(duplicate_by_uid(self.test_case.uid))


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


class SerializationTests(PluginApiTestBase):
    """Tests of ``testcanvas.utilities.serialization``."""

    def setUp(self) -> None:
        """Turn n2 into a SUBFLOW node referencing a map the reader cannot read."""
        super().setUp()
        FlowNode.objects.filter(pk=self.node2.pk).update(node_type=FlowNode.SUBFLOW, sub_flow=self.map_other)

    def _node(self, data: dict, local_id: str) -> dict:
        """Return the serialized node with ``local_graph_id == local_id``."""
        return next(n for n in data["nodes"] if n["local_graph_id"] == local_id)

    def test_subflow_is_redacted_for_users_who_cannot_read_it(self) -> None:
        """The reader sees the node but not the referenced map."""
        data = serialize_flow_overview(self.reader, self.map_child)
        self.assertIsNone(self._node(data, "n2")["sub_flow_uid"])
        self.assertIsNone(self._node(data, "n2")["sub_flow_name"])

        data = serialize_flow_overview(self.superuser, self.map_child)
        self.assertEqual(self._node(data, "n2")["sub_flow_uid"], self.map_other.uid)

    def test_overview_tree_exposes_uids_only(self) -> None:
        """The nested tree contains the chain, identified by UIDs."""
        data = serialize_flow_overview(self.reader, self.map_child, include_test_cases=True)
        self.assertEqual(data["uid"], self.map_child.uid)
        story = self._node(data, "n1")["user_stories"][0]
        self.assertEqual(story["uid"], self.story.uid)
        self.assertNotIn("id", story)
        criterion = story["acceptance_criteria"][0]
        self.assertEqual(criterion["uid"], self.criterion.uid)
        self.assertEqual(criterion["test_cases"][0]["uid"], self.test_case.uid)

    def test_overview_requires_read_access(self) -> None:
        """Unreadable maps are reported as not found."""
        with self.assertRaises(ObjectNotFound):
            serialize_flow_overview(self.reader, self.map_other)

