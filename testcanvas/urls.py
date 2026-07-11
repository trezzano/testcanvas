from django.urls import path

from . import views

app_name = 'testcanvas'

urlpatterns = [

    # main map page
    path('', views.map_list, name='map_list'),
    path('create/', views.map_create, name='map_create'),
    path('<int:pk>/save/', views.map_save, name='map_save'),
    path('<int:pk>/delete/', views.map_delete, name='map_delete'),
    path('<int:pk>/', views.map_editor, name='map_editor'),

    # traceability page
    path('flow-node/<int:node_id>/traceability/', views.flow_node_traceability, name='flow_node_traceability'),

    # user story
    path('<int:pk>/node/<str:node_id>/user-stories/', views.node_user_stories, name='node_user_stories'),
    path('flow-node/<int:node_id>/user-stories/manage/', views.user_story_manage, name='user_story_manage'),
    path('flow-node/<int:node_id>/user-stories/<int:pk>/edit/', views.user_story_edit, name='user_story_edit'),
    path('flow-node/<int:node_id>/user-stories/<int:pk>/delete/', views.user_story_delete, name='user_story_delete'),

    # acceptance criteria
    path('user-stories/<int:user_story_id>/acceptance-criteria/manage/', views.acceptance_criterion_manage, name='acceptance_criterion_manage'),
    path('acceptance-criteria/<int:pk>/edit/', views.acceptance_criterion_edit, name='acceptance_criterion_edit'),
    path('acceptance-criteria/<int:pk>/delete/', views.acceptance_criterion_delete, name='acceptance_criterion_delete'),

    # test cases
    path('flow-node/<int:node_id>/test-cases/manage/', views.test_case_manage, name='test_case_manage'),
    path('flow-node/<int:node_id>/test-cases/<int:pk>/delete/', views.test_case_delete, name='test_case_delete'),
    path('test-cases/<int:pk>/edit/', views.test_case_edit, name='test_case_edit'),
]

