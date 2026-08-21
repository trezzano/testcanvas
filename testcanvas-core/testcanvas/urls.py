from django.urls import path

from .views.standard_views import (
    # index / authentication
    index,
    logout_view,
    # main map page
    map_list,
    map_create,
    map_save,
    map_delete,
    map_editor,
    map_editor_by_uid,
    map_subflow_usage,
    # traceability page
    flow_node_traceability,
    flow_node_traceability_matrix,
    set_traceability_view,
    # shared HTMX detail cards (US / AC / TC), reused by graph and RTM table
    user_story_detail,
    acceptance_criterion_detail,
    test_case_detail,
    # user story
    node_user_stories,
    user_story_manage,
    user_story_edit,
    user_story_delete,
    # acceptance criteria
    acceptance_criterion_manage,
    acceptance_criterion_edit,
    acceptance_criterion_delete,
    node_acceptance_criteria,
    # test cases
    test_case_manage,
    test_case_edit,
    test_case_delete,
    # application maps collections
    collection_list,
    collection_create,
    collection_edit,
    collection_delete,
)
from .views.collection_hierarchy_views import (
    # nested (folder/sub-folder) hierarchy operations
    collection_tree,
    collection_children,
    collection_move,
    collection_detail,
)

app_name = 'testcanvas'

urlpatterns = [
    # index / authentication
    path('', index, name='index'),
    path('logout/', logout_view, name='logout'),
    # main map page
    path('map_list/', map_list, name='map_list'),
    path('create/', map_create, name='map_create'),
    path('<int:pk>/save/', map_save, name='map_save'),
    path('<int:pk>/delete/', map_delete, name='map_delete'),
    path('<int:pk>/subflow-usage/', map_subflow_usage, name='map_subflow_usage'),
    path('flow/<str:flow_uid>/', map_editor_by_uid, name='map_editor_by_uid'),
    path('<int:pk>/', map_editor, name='map_editor'),

    # traceability page
    path('flow-node/<int:node_id>/traceability/', flow_node_traceability, name='flow_node_traceability'),
    path('flow-node/<int:node_id>/traceability/matrix/', flow_node_traceability_matrix, name='flow_node_traceability_matrix'),
    # single control point to pick the preferred traceability view (graph/matrix)
    path('traceability/view/', set_traceability_view, name='set_traceability_view'),

    # shared HTMX detail cards, reused by both the graph and the RTM table
    path('user-stories/<int:pk>/detail/', user_story_detail, name='user_story_detail'),
    path('acceptance-criteria/<int:pk>/detail/', acceptance_criterion_detail, name='acceptance_criterion_detail'),
    path('test-cases/<int:pk>/detail/', test_case_detail, name='test_case_detail'),

    # user story
    path('<int:pk>/node/<str:node_id>/user-stories/', node_user_stories, name='node_user_stories'),
    path('flow-node/<int:node_id>/user-stories/manage/', user_story_manage, name='user_story_manage'),
    path('flow-node/<int:node_id>/user-stories/<int:pk>/edit/', user_story_edit, name='user_story_edit'),
    path('flow-node/<int:node_id>/user-stories/<int:pk>/delete/', user_story_delete, name='user_story_delete'),

    # acceptance criteria
    path('user-stories/<int:user_story_id>/acceptance-criteria/manage/', acceptance_criterion_manage, name='acceptance_criterion_manage'),
    path('flow-node/<int:node_id>/acceptance-criteria/', node_acceptance_criteria, name='node_acceptance_criteria'),
    path('acceptance-criteria/<int:pk>/edit/', acceptance_criterion_edit, name='acceptance_criterion_edit'),
    path('acceptance-criteria/<int:pk>/delete/', acceptance_criterion_delete, name='acceptance_criterion_delete'),

    # test cases
    path('acceptance-criteria/<int:acceptance_criterion_id>/test-cases/manage/', test_case_manage, name='test_case_manage'),
    path('test-cases/<int:pk>/edit/', test_case_edit, name='test_case_edit'),
    path('test-cases/<int:pk>/delete/', test_case_delete, name='test_case_delete'),


    # application maps collections (logical grouping layer)
    path('collections/', collection_list, name='collection_list'),
    path('collections/create/', collection_create, name='collection_create'),
    path('collections/<int:pk>/edit/', collection_edit, name='collection_edit'),
    path('collections/<int:pk>/delete/', collection_delete, name='collection_delete'),

    # application maps collections — nested (folder/sub-folder) hierarchy
    path('collections/tree/', collection_tree, name='collection_tree'),
    path('collections/<int:pk>/children/', collection_children, name='collection_children'),
    path('collections/<int:pk>/move/', collection_move, name='collection_move'),
    path('collections/<int:pk>/detail/', collection_detail, name='collection_detail'),
]

