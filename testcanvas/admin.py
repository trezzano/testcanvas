from django.contrib import admin

from .models import (
    AcceptanceCriterion,
    ApplicationMap,
    FlowNode,
    TestCase,
    UserStory,
)


class FlowNodeInline(admin.TabularInline):
    model = FlowNode
    extra = 0
    fields = ("local_graph_id", "title", "description")
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


@admin.register(ApplicationMap)
class ApplicationMapAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "node_count", "created_at")
    search_fields = ("name",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    inlines = (FlowNodeInline,)

    @admin.display(description="Nodes")
    def node_count(self, obj):
        return obj.relational_nodes.count()


@admin.register(FlowNode)
class FlowNodeAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "local_graph_id", "application_map")
    list_filter = ("application_map",)
    search_fields = ("title", "description")
    list_select_related = ("application_map",)
    autocomplete_fields = ("application_map",)
    inlines = (UserStoryInline,)


@admin.register(UserStory)
class UserStoryAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "title", "flow_node")
    list_filter = ("flow_node__application_map",)
    search_fields = ("code", "title", "description")
    list_select_related = ("flow_node",)
    autocomplete_fields = ("flow_node",)
    inlines = (AcceptanceCriterionInline,)


@admin.register(AcceptanceCriterion)
class AcceptanceCriterionAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "user_story")
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

