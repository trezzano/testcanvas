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
    # traceability page
    flow_node_traceability,
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
    test_case_delete,
    test_case_edit,
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
    path('<int:pk>/', map_editor, name='map_editor'),

    # traceability page
    path('flow-node/<int:node_id>/traceability/', flow_node_traceability, name='flow_node_traceability'),

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
    path('flow-node/<int:node_id>/test-cases/manage/', test_case_manage, name='test_case_manage'),
    path('flow-node/<int:node_id>/test-cases/<int:pk>/delete/', test_case_delete, name='test_case_delete'),
    path('test-cases/<int:pk>/edit/', test_case_edit, name='test_case_edit'),
]

