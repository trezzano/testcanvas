from django.contrib import admin

from .models import (
    AcceptanceCriterion,
    ApplicationMap,
    ApplicationMapsCollection,
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
    fields = ("node_uid", "local_graph_id", "title", "node_type", "sub_flow", "description")
    # node_uid is auto-generated (editable=False), so expose it read-only.
    readonly_fields = ("node_uid",)
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
    fields = ("code", "text")
    show_change_link = True


class TestCaseInline(admin.TabularInline):
    # TestCase now relates to AcceptanceCriterion via a ManyToManyField, so we
    # inline the auto-created through model instead of TestCase directly.
    model = TestCase.criteria.through
    extra = 0
    verbose_name = "Test Case link"
    verbose_name_plural = "Test Case links"
    autocomplete_fields = ("testcase",)
    show_change_link = True


class ApplicationMapInline(admin.TabularInline):
    """Inline listing the maps that belong to a collection."""

    model = ApplicationMap
    extra = 0
    fields = ("name", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(ApplicationMapsCollection)
class ApplicationMapsCollectionAdmin(admin.ModelAdmin):
    """Admin for the logical grouping layer over ApplicationMap."""

    list_display = ("id", "title", "background_color", "map_count", "created_at")
    search_fields = ("title", "description")
    date_hierarchy = "created_at"
    ordering = ("title",)
    readonly_fields = ("created_at",)
    inlines = (ApplicationMapInline,)

    @admin.display(description="Maps")
    def map_count(self, obj):
        return obj.maps.count()


@admin.register(ApplicationMap)
class ApplicationMapAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "collection", "node_count", "created_at", "flow_uid")
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
    list_display = ("id", "node_uid", "title", "local_graph_id", "node_type", "sub_flow", "application_map")
    list_filter = ("node_type", "application_map")
    search_fields = ("node_uid", "title", "description")
    list_select_related = ("application_map", "sub_flow")
    # node_uid is auto-generated (editable=False), so expose it read-only.
    readonly_fields = ("node_uid",)
    autocomplete_fields = ("application_map", "sub_flow")
    inlines = (UserStoryInline,)


@admin.register(UserStory)
class UserStoryAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "title", "flow_node", "user_story_uid")
    list_filter = ("flow_node__application_map",)
    search_fields = ("code", "title", "description")
    list_select_related = ("flow_node",)
    autocomplete_fields = ("flow_node",)
    inlines = (AcceptanceCriterionInline,)


@admin.register(AcceptanceCriterion)
class AcceptanceCriterionAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "user_story", "ac_uid")
    list_filter = ("user_story__flow_node__application_map",)
    search_fields = ("code", "text")
    list_select_related = ("user_story",)
    autocomplete_fields = ("user_story",)
    inlines = (TestCaseInline,)


@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "test_code", "title", "status", "criteria_list")
    list_filter = ("status", "criteria__user_story__flow_node__application_map")
    search_fields = ("test_code", "title", "preconditions", "steps", "expected_result")
    autocomplete_fields = ("criteria",)
    filter_horizontal = ("criteria",)
    list_editable = ("status",)

    def get_queryset(self, request):
        # Prefetch the M2M so criteria_list doesn't trigger N+1 queries.
        return super().get_queryset(request).prefetch_related("criteria")

    @admin.display(description="Criteria")
    def criteria_list(self, obj):
        return ", ".join(c.code for c in obj.criteria.all()) or "—"

