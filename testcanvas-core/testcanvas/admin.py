from django.contrib import admin

from .models import (
    AcceptanceCriterion,
    ApplicationMap,
    ApplicationMapsCollection,
    CollectionPermission,
    FieldVisibilityPreference,
    FlowNode,
    TestCase,
    UserStory,
)


class FlowNodeInline(admin.TabularInline):
    model = FlowNode
    # Restrict to the parent map's own nodes; `fk_name` disambiguates the two
    # FKs pointing to ApplicationMap (application_map vs. sub_flow).
    fk_name = "application_map"
    extra = 0
    fields = ("uid", "local_graph_id", "title", "node_type", "sub_flow", "description")
    # uid is auto-generated (editable=False), so expose it read-only.
    readonly_fields = ("uid",)
    autocomplete_fields = ("sub_flow",)
    show_change_link = True


class UserStoryInline(admin.TabularInline):
    model = UserStory
    extra = 0
    fields = ("code", "title", "description")
    show_change_link = True


class AcceptanceCriterionInline(admin.TabularInline):
    model = AcceptanceCriterion
    extra = 0
    fields = ("code", "criterion_type", "description", "gherkin_text")
    show_change_link = True


class TestCaseInline(admin.TabularInline):
    model = TestCase
    extra = 0
    fields = ("code", "description")
    show_change_link = True


class CollectionPermissionInline(admin.TabularInline):
    """Inline to grant read/write access on a collection to users or groups.

    Grants cascade to every sub-collection and contained flow (see
    ``testcanvas.utilities.permissions``).
    """

    model = CollectionPermission
    extra = 1
    fields = ("user", "group", "can_read", "can_write")
    autocomplete_fields = ("user", "group")


@admin.register(ApplicationMapsCollection)
class ApplicationMapsCollectionAdmin(admin.ModelAdmin):
    """Admin for the logical grouping layer over ApplicationMap."""

    list_display = ("id", "title", "parent", "background_color", "created_at")
    search_fields = ("title", "description")
    date_hierarchy = "created_at"
    ordering = ("title",)
    readonly_fields = ("created_at",)
    inlines = (CollectionPermissionInline,)


@admin.register(CollectionPermission)
class CollectionPermissionAdmin(admin.ModelAdmin):
    """Flat admin view of every collection grant, handy to audit access."""

    list_display = ("id", "collection", "user", "group", "can_read", "can_write")
    list_filter = ("can_read", "can_write", "collection")
    search_fields = ("collection__title", "user__username", "group__name")
    list_select_related = ("collection", "user", "group")
    autocomplete_fields = ("collection", "user", "group")


@admin.register(ApplicationMap)
class ApplicationMapAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "collection", "node_count", "created_at", "uid")
    list_filter = ("collection",)
    search_fields = ("name",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    autocomplete_fields = ("collection",)
    inlines = (FlowNodeInline,)

    @admin.display(description="Nodes")
    def node_count(self, obj):
        return obj.relational_nodes.count()


@admin.register(FlowNode)
class FlowNodeAdmin(admin.ModelAdmin):
    list_display = ("id", "uid", "title", "local_graph_id", "node_type", "sub_flow", "application_map")
    list_filter = ("node_type", "application_map")
    search_fields = ("uid", "title", "description")
    list_select_related = ("application_map", "sub_flow")
    # uid is auto-generated (editable=False), so expose it read-only.
    readonly_fields = ("uid",)
    autocomplete_fields = ("application_map", "sub_flow")
    inlines = (UserStoryInline,)


@admin.register(UserStory)
class UserStoryAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "title", "flow_node", "uid")
    list_filter = ("flow_node__application_map",)
    search_fields = ("code", "title", "description")
    list_select_related = ("flow_node",)
    autocomplete_fields = ("flow_node",)
    inlines = (AcceptanceCriterionInline,)


@admin.register(AcceptanceCriterion)
class AcceptanceCriterionAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "criterion_type", "user_story", "has_gherkin", "uid")
    list_filter = ("user_story__flow_node__application_map",)
    search_fields = ("code", "description", "gherkin_text")
    list_select_related = ("user_story",)
    autocomplete_fields = ("user_story",)
    inlines = (TestCaseInline,)


@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "acceptance_criterion", "uid")
    list_filter = ("acceptance_criterion__user_story__flow_node__application_map",)
    search_fields = ("code", "description", "uid")
    list_select_related = ("acceptance_criterion",)
    # uid is auto-generated (editable=False), so expose it read-only.
    readonly_fields = ("uid",)
    autocomplete_fields = ("acceptance_criterion",)


@admin.register(FieldVisibilityPreference)
class FieldVisibilityPreferenceAdmin(admin.ModelAdmin):
    """Admin for global optional field visibility toggles."""

    list_display = ("id", "target_model", "field_name", "is_visible", "order")
    list_filter = ("target_model", "is_visible")
    list_editable = ("is_visible", "order")
    search_fields = ("field_name", "target_model")
