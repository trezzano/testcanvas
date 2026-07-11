import json

import networkx as nx
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import AcceptanceCriterion, ApplicationMap, FlowNode, TestCase, UserStory
from .forms import AcceptanceCriterionForm, TestCaseForm, UserStoryForm

def user_story_manage(request, node_id):
    """List and create UserStories for a given FlowNode.

    Standard Django view: GET renders the list plus an empty create form,
    POST validates the form and creates a new UserStory bound to the node.
    """
    flow_node = get_object_or_404(
        FlowNode.objects.select_related('application_map'),
        pk=node_id,
    )

    if request.method == 'POST':
        form = UserStoryForm(request.POST)
        if form.is_valid():
            user_story = form.save(commit=False)
            user_story.flow_node = flow_node
            user_story.save()
            messages.success(request, f"User Story '{user_story.code}' created.")
            return redirect('testcanvas:user_story_manage', node_id=flow_node.pk)
    else:
        form = UserStoryForm()

    user_stories = flow_node.user_stories.order_by('code')
    return render(request, 'testcanvas/user_story_manage.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_stories': user_stories,
        'form': form,
    })

def user_story_edit(request, node_id, pk):
    """Edit an existing UserStory belonging to the given FlowNode."""
    flow_node = get_object_or_404(
        FlowNode.objects.select_related('application_map'),
        pk=node_id,
    )
    user_story = get_object_or_404(UserStory, pk=pk, flow_node=flow_node)

    if request.method == 'POST':
        form = UserStoryForm(request.POST, instance=user_story)
        if form.is_valid():
            form.save()
            messages.success(request, f"User Story '{user_story.code}' updated.")
            return redirect('testcanvas:user_story_manage', node_id=flow_node.pk)
    else:
        form = UserStoryForm(instance=user_story)

    return render(request, 'testcanvas/user_story_edit.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_story': user_story,
        'form': form,
    })

@require_POST
def user_story_delete(request, node_id, pk):
    """Delete a UserStory belonging to the given FlowNode."""
    flow_node = get_object_or_404(FlowNode, pk=node_id)
    user_story = get_object_or_404(UserStory, pk=pk, flow_node=flow_node)
    code = user_story.code
    user_story.delete()
    messages.success(request, f"User Story '{code}' deleted.")
    return redirect('testcanvas:user_story_manage', node_id=flow_node.pk)

def acceptance_criterion_manage(request, user_story_id):
    """List and create AcceptanceCriteria for a given UserStory.

    Standard Django view: GET renders the list plus an empty create form,
    POST validates the form and creates a new AcceptanceCriterion bound to
    the user story. Mirrors ``user_story_manage``.
    """
    user_story = get_object_or_404(
        UserStory.objects.select_related('flow_node__application_map'),
        pk=user_story_id,
    )
    flow_node = user_story.flow_node

    if request.method == 'POST':
        form = AcceptanceCriterionForm(request.POST)
        if form.is_valid():
            criterion = form.save(commit=False)
            criterion.user_story = user_story
            criterion.save()
            messages.success(request, f"Acceptance Criterion '{criterion.code}' created.")
            return redirect('testcanvas:acceptance_criterion_manage', user_story_id=user_story.pk)
    else:
        form = AcceptanceCriterionForm()

    criteria = user_story.criteria.order_by('code')
    return render(request, 'testcanvas/acceptance_criterion_manage.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_story': user_story,
        'criteria': criteria,
        'form': form,
    })

def acceptance_criterion_edit(request, pk):
    """Edit an existing AcceptanceCriterion following the UserStory edit pattern."""
    criterion = get_object_or_404(
        AcceptanceCriterion.objects.select_related(
            'user_story__flow_node__application_map',
        ),
        pk=pk,
    )
    user_story = criterion.user_story
    flow_node = user_story.flow_node

    if request.method == 'POST':
        form = AcceptanceCriterionForm(request.POST, instance=criterion)
        if form.is_valid():
            form.save()
            messages.success(request, f"Acceptance Criterion '{criterion.code}' updated.")
            return redirect('testcanvas:acceptance_criterion_manage', user_story_id=user_story.pk)
    else:
        form = AcceptanceCriterionForm(instance=criterion)

    return render(request, 'testcanvas/acceptance_criterion_edit.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_story': user_story,
        'criterion': criterion,
        'form': form,
    })

@require_POST
def acceptance_criterion_delete(request, pk):
    """Delete an AcceptanceCriterion, returning to its UserStory manage page."""
    criterion = get_object_or_404(
        AcceptanceCriterion.objects.select_related('user_story'),
        pk=pk,
    )
    user_story = criterion.user_story
    code = criterion.code
    criterion.delete()
    messages.success(request, f"Acceptance Criterion '{code}' deleted.")
    return redirect('testcanvas:acceptance_criterion_manage', user_story_id=user_story.pk)

def test_case_manage(request, node_id):
    """List and create TestCases for a given FlowNode.

    Test cases are linked (M2M) to AcceptanceCriteria; here we scope them to a
    single FlowNode: the list shows every test case that verifies at least one
    criterion belonging to the node, and creation limits the selectable criteria
    to that same node. Mirrors ``acceptance_criterion_manage``.
    """
    flow_node = get_object_or_404(
        FlowNode.objects.select_related('application_map'),
        pk=node_id,
    )

    # Acceptance criteria available within this flow node (used to scope the form).
    node_criteria = AcceptanceCriterion.objects.filter(
        user_story__flow_node=flow_node,
    ).select_related('user_story')

    if request.method == 'POST':
        form = TestCaseForm(request.POST)
        form.fields['criteria'].queryset = node_criteria
        if form.is_valid():
            test_case = form.save()
            messages.success(request, f"Test Case '{test_case.test_code}' created.")
            return redirect('testcanvas:test_case_manage', node_id=flow_node.pk)
    else:
        form = TestCaseForm()
        form.fields['criteria'].queryset = node_criteria

    test_cases = (
        TestCase.objects
        .filter(criteria__user_story__flow_node=flow_node)
        .prefetch_related('criteria')
        .distinct()
        .order_by('test_code')
    )

    return render(request, 'testcanvas/test_case_manage.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'test_cases': test_cases,
        'has_criteria': node_criteria.exists(),
        'form': form,
    })


@require_POST
def test_case_delete(request, node_id, pk):
    """Delete a TestCase, returning to the FlowNode test-case manage page."""
    flow_node = get_object_or_404(FlowNode, pk=node_id)
    test_case = get_object_or_404(
        TestCase.objects.filter(criteria__user_story__flow_node=flow_node).distinct(),
        pk=pk,
    )
    code = test_case.test_code
    test_case.delete()
    messages.success(request, f"Test Case '{code}' deleted.")
    return redirect('testcanvas:test_case_manage', node_id=flow_node.pk)


def test_case_edit(request, pk):
    """Edit an existing TestCase following the UserStory edit pattern."""
    test_case = get_object_or_404(
        TestCase.objects.prefetch_related('criteria__user_story__flow_node'),
        pk=pk,
    )

    # Derive the owning flow node (via the first linked criterion) for breadcrumbs/back link.
    first_criterion = test_case.criteria.select_related(
        'user_story__flow_node__application_map',
    ).first()
    flow_node = first_criterion.user_story.flow_node if first_criterion else None
    application_map = flow_node.application_map if flow_node else None

    if request.method == 'POST':
        form = TestCaseForm(request.POST, instance=test_case)
        if flow_node is not None:
            form.fields['criteria'].queryset = AcceptanceCriterion.objects.filter(
                user_story__flow_node=flow_node,
            ).select_related('user_story')
        if form.is_valid():
            form.save()
            messages.success(request, f"Test Case '{test_case.test_code}' updated.")
            return redirect('testcanvas:test_case_edit', pk=test_case.pk)
    else:
        form = TestCaseForm(instance=test_case)
        if flow_node is not None:
            form.fields['criteria'].queryset = AcceptanceCriterion.objects.filter(
                user_story__flow_node=flow_node,
            ).select_related('user_story')

    return render(request, 'testcanvas/test_case_edit.html', {
        'flow_node': flow_node,
        'application_map': application_map,
        'test_case': test_case,
        'form': form,
    })

def flow_node_traceability(request, node_id):
    """Render the ISTQB traceability graph for a single FlowNode.

    Starting from a ``FlowNode`` id it visualises the relations
    ``UserStory -> AcceptanceCriterion -> TestCase`` using Cytoscape.js
    (inspired by ``bjtapai/nuova_interfaccia.html``).
    """
    flow_node = get_object_or_404(
        FlowNode.objects.select_related('application_map'),
        pk=node_id,
    )

    user_stories_payload = []
    acceptance_map = {}   # ac.pk -> dict (deduplicated)
    test_cases_map = {}   # tc.pk -> dict (deduplicated)

    user_stories = (
        flow_node.user_stories
        .prefetch_related('criteria__test_cases')
        .all()
    )

    for story in user_stories:
        criteria_ids = []
        for criterion in story.criteria.all():
            ac_id = f"AC_{criterion.pk}"
            criteria_ids.append(ac_id)

            if ac_id not in acceptance_map:
                acceptance_map[ac_id] = {
                    'id': ac_id,
                    'code': criterion.code,
                    'description': criterion.text,
                }

            for test_case in criterion.test_cases.all():
                tc_id = f"TC_{test_case.pk}"
                entry = test_cases_map.setdefault(tc_id, {
                    'id': tc_id,
                    'code': test_case.test_code,
                    'name': test_case.title,
                    'status': test_case.get_status_display(),
                    'verifies': [],
                })
                if ac_id not in entry['verifies']:
                    entry['verifies'].append(ac_id)

        user_stories_payload.append({
            'id': f"US_{story.pk}",
            'code': story.code,
            'name': story.title,
            'description': story.description,
            'acceptance_criteria': criteria_ids,
        })

    graph_data = {
        'user_stories': user_stories_payload,
        'acceptance_criteria': list(acceptance_map.values()),
        'test_cases': list(test_cases_map.values()),
    }

    context = {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'graph_data_json': json.dumps(graph_data),
    }
    return render(request, 'testcanvas/flow_node_traceability.html', context)

def map_list(request):
    """List every ApplicationMap and allow the creation of a new one."""
    maps = ApplicationMap.objects.order_by('-created_at')
    return render(request, 'testcanvas/map_list.html', {'maps': maps})

@require_POST
def map_create(request):
    """Create a new (empty) ApplicationMap and jump straight into the editor."""
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, "The flow name cannot be empty.")
        return redirect('testcanvas:map_list')

    application_map = ApplicationMap.objects.create(name=name)
    messages.success(request, f"Flow '{name}' created.")
    return redirect('testcanvas:map_editor', pk=application_map.pk)

def map_editor(request, pk):
    """Render the Cytoscape.js editor for a given ApplicationMap."""
    application_map = get_object_or_404(ApplicationMap, pk=pk)

    # graph_data is already stored in Cytoscape format; hand it to the template as JSON.
    graph_data = application_map.graph_data or {}
    context = {
        'application_map': application_map,
        'graph_data_json': json.dumps(graph_data),
    }
    return render(request, 'testcanvas/map_editor.html', context)

@require_POST
def map_save(request, pk):
    """AJAX endpoint: persist the Cytoscape graph coming from the front-end.

    The payload is the ``elements`` object produced by ``cy.json()``. We normalise
    it into a NetworkX/Cytoscape compatible structure (adding the ``value`` key that
    ``nx.cytoscape_graph`` expects) while preserving node positions, so the layout is
    restored the next time the editor is opened.
    """
    application_map = get_object_or_404(ApplicationMap, pk=pk)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)

    elements = payload.get('elements')
    if elements is None:
        return JsonResponse({'ok': False, 'error': "Missing 'elements' key."}, status=400)

    # cy.json() groups elements as {'nodes': [...], 'edges': [...]}, but also accept a flat list.
    if isinstance(elements, dict):
        raw_nodes = elements.get('nodes', [])
        raw_edges = elements.get('edges', [])
    else:
        raw_nodes = [e for e in elements if 'source' not in e.get('data', {})]
        raw_edges = [e for e in elements if 'source' in e.get('data', {})]

    node_ids = set()
    norm_nodes = []
    for n in raw_nodes:
        data = dict(n.get('data', {}))
        node_id = data.get('id')
        if node_id is None:
            return JsonResponse({'ok': False, 'error': 'A node is missing its id.'}, status=400)
        data.setdefault('name', node_id)
        data['value'] = node_id  # required by nx.cytoscape_graph
        node_ids.add(node_id)
        entry = {'data': data}
        if 'position' in n:
            entry['position'] = n['position']
        norm_nodes.append(entry)

    norm_edges = []
    for e in raw_edges:
        data = dict(e.get('data', {}))
        if data.get('source') not in node_ids or data.get('target') not in node_ids:
            # Drop dangling edges whose endpoints no longer exist.
            continue
        norm_edges.append({'data': data})

    graph_data = {
        'data': payload.get('data', []),
        'directed': True,
        'multigraph': False,
        'elements': {'nodes': norm_nodes, 'edges': norm_edges},
    }

    # Sanity check: make sure NetworkX can rebuild the graph from what we store.
    try:
        nx.cytoscape_graph(graph_data)
    except Exception as exc:  # noqa: BLE001 - surface any conversion error to the client
        return JsonResponse({'ok': False, 'error': f'Graph validation failed: {exc}'}, status=400)

    application_map.graph_data = graph_data

    # Allow renaming from the editor as well.
    new_name = (payload.get('name') or '').strip()
    if new_name:
        application_map.name = new_name

    application_map.save()
    return JsonResponse({
        'ok': True,
        'graph_data': application_map.graph_data,
        'name': application_map.name,
    })

def node_user_stories(request, pk, node_id):
    """HTMX endpoint: render the UserStories linked to a graph node (via FlowNode) as an HTML partial."""
    application_map = get_object_or_404(ApplicationMap, pk=pk)
    flow_node = application_map.relational_nodes.filter(local_graph_id=str(node_id)).first()

    user_stories = flow_node.user_stories.all() if flow_node else []
    return render(request, 'testcanvas/_user_stories.html', {
        'flow_node': flow_node,
        'node_id': node_id,
        'user_stories': user_stories,
    })

@require_POST
def map_delete(request, pk):
    """Delete an ApplicationMap."""
    application_map = get_object_or_404(ApplicationMap, pk=pk)
    name = application_map.name
    application_map.delete()
    messages.success(request, f"Flow '{name}' deleted.")
    return redirect('testcanvas:map_list')

