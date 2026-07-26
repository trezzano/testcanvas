import json

import networkx as nx
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from testcanvas.models import AcceptanceCriterion, ApplicationMap, ApplicationMapsCollection, FlowNode, TestCase, UserStory
from testcanvas.forms import AcceptanceCriterionForm, ApplicationMapsCollectionForm, TestCaseForm, UserStoryForm
from testcanvas.context_processors import TRACEABILITY_SESSION_KEY, TRACEABILITY_URL_NAMES

def index(request):
    """Render the login page and authenticate users.

    The landing page doubles as the sign-in screen: on GET it shows the login
    form, on POST it validates the credentials with Django's
    ``AuthenticationForm`` and, on success, starts the session and redirects to
    the flow list. Already-authenticated users skip the form entirely.

    Args:
        request: The incoming HTTP request.

    Returns:
        An ``HttpResponse`` rendering the login page, or a redirect to the
        flow list once the user is authenticated.
    """
    # Authenticated users have no reason to see the login screen again.
    if request.user.is_authenticated:
        return redirect('testcanvas:map_list')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            # ``get_user`` returns the user validated by the form's clean step.
            auth_login(request, form.get_user())
            messages.success(request, f"Welcome back, {form.get_user().username}!")
            return redirect('testcanvas:map_list')
    else:
        form = AuthenticationForm(request)

    return render(request, 'testcanvas/index.html', {'form': form})

@require_POST
def logout_view(request):
    """Log the current user out and return to the login page.

    Args:
        request: The incoming HTTP request (POST only, for CSRF safety).

    Returns:
        A redirect to the login page.
    """
    auth_logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('testcanvas:index')

@login_required
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

@login_required
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
@login_required
def user_story_delete(request, node_id, pk):
    """Delete a UserStory belonging to the given FlowNode."""
    flow_node = get_object_or_404(FlowNode, pk=node_id)
    user_story = get_object_or_404(UserStory, pk=pk, flow_node=flow_node)
    code = user_story.code
    user_story.delete()
    messages.success(request, f"User Story '{code}' deleted.")
    return redirect('testcanvas:user_story_manage', node_id=flow_node.pk)

@login_required
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

@login_required
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
@login_required
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

@login_required
def node_acceptance_criteria(request, node_id):
    """List every Acceptance Criterion of a FlowNode, grouped by User Story.

    Acceptance Criteria always belong to a specific User Story, so a flow node
    can hold criteria across several stories. This read-only overview shows each
    story of the node together with its criteria and a link to manage them,
    giving the traceability page a single AC-focused destination regardless of
    how many User Stories the node has.

    Args:
        request: The incoming HTTP request.
        node_id: Primary key of the ``FlowNode`` to inspect.

    Returns:
        An ``HttpResponse`` rendering the acceptance-criteria overview.
    """
    flow_node = get_object_or_404(
        FlowNode.objects.select_related('application_map'),
        pk=node_id,
    )
    user_stories = (
        flow_node.user_stories
        .prefetch_related('criteria')
        .order_by('code')
    )
    return render(request, 'testcanvas/acceptance_criterion_overview.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_stories': user_stories,
    })

@login_required
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
@login_required
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

@login_required
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

@login_required
def flow_node_traceability(request, node_id):
    """Render the ISTQB traceability graph for a single FlowNode.

    Visualises the relations ``UserStory -> AcceptanceCriterion -> TestCase``
    with Cytoscape.js. All data shaping happens here: the view emits a
    ready-to-use Cytoscape ``elements`` list (nodes + edges) with every display
    value and edit URL already baked into each node's ``data``. The front-end
    only feeds this list to Cytoscape and lays it out, so the JS stays thin.

    Args:
        request: The incoming HTTP request.
        node_id: Primary key of the ``FlowNode`` to visualise.

    Returns:
        An ``HttpResponse`` rendering the traceability page.
    """
    flow_node = get_object_or_404(
        FlowNode.objects.select_related('application_map'),
        pk=node_id,
    )

    user_stories = list(
        flow_node.user_stories
        .prefetch_related('criteria__test_cases')
        .all()
    )

    # Cytoscape node/edge elements, built directly from the ORM objects.
    nodes = []
    edges = []
    seen_ac = {}          # criterion.pk -> covered flag (dedup across stories)
    seen_tc = set()       # test_case.pk already added as a node
    coverage_rows = []    # server-rendered "AC coverage" sidebar list

    for story in user_stories:
        us_id = f"US_{story.pk}"
        # Only the data Cytoscape needs to draw and identify the node is sent.
        # The full detail (Agile fields, edit link, etc.) is fetched on demand
        # from the shared HTMX detail partial via ``detail_url``.
        nodes.append({'data': {
            'id': us_id,
            'label': story.code,
            'type': 'us',
            'code': story.code,
            # URL of the HTMX detail card opened when the node is tapped.
            'detail_url': reverse('testcanvas:user_story_detail', args=[story.pk]),
        }})

        for criterion in story.criteria.all():
            ac_id = f"AC_{criterion.pk}"
            covered = criterion.test_cases.exists()

            # A criterion can belong to several stories: add the node once but
            # always draw the US -> AC decomposition edge.
            if criterion.pk not in seen_ac:
                seen_ac[criterion.pk] = covered
                nodes.append({'data': {
                    'id': ac_id,
                    'label': criterion.code,
                    'type': 'ac',
                    'covered': covered,
                    'code': criterion.code,
                    'detail_url': reverse('testcanvas:acceptance_criterion_detail', args=[criterion.pk]),
                }})
                coverage_rows.append({
                    'code': criterion.code,
                    'covered': covered,
                    'count': criterion.test_cases.count(),
                })
            edges.append({'data': {'id': f"e_{us_id}_{ac_id}", 'source': us_id, 'target': ac_id, 'kind': 'decompose'}})

            for test_case in criterion.test_cases.all():
                tc_id = f"TC_{test_case.pk}"
                if test_case.pk not in seen_tc:
                    seen_tc.add(test_case.pk)
                    nodes.append({'data': {
                        'id': tc_id,
                        'label': test_case.test_code,
                        'type': 'tc',
                        'code': test_case.test_code,
                        'detail_url': reverse('testcanvas:test_case_detail', args=[test_case.pk]),
                    }})
                # Edge drawn AC -> TC; the front-end lays out US | AC | TC in
                # three columns and renders the arrow on the source side so it
                # still visually points at the AC being verified.
                edges.append({'data': {'id': f"e_{tc_id}_{ac_id}", 'source': ac_id, 'target': tc_id, 'kind': 'verify'}})

    # --- Counters and coverage, computed server-side so the template (not JS)
    # renders the stats bar, the coverage list and the lane button states. ---
    us_count = len(user_stories)
    ac_count = len(seen_ac)
    tc_count = len(seen_tc)
    covered_count = sum(1 for covered in seen_ac.values() if covered)
    uncovered_count = ac_count - covered_count

    context = {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        # Ready-to-use Cytoscape elements: the JS feeds this straight in.
        'elements_json': json.dumps(nodes + edges),
        'coverage_rows': coverage_rows,
        'us_count': us_count,
        'ac_count': ac_count,
        'tc_count': tc_count,
        'covered_count': covered_count,
        'uncovered_count': uncovered_count,
    }
    return render(request, 'testcanvas/flow_node_traceability.html', context)


@login_required
def flow_node_traceability_matrix(request, node_id):
    """Render the ISTQB Requirements Traceability Matrix (RTM) for a FlowNode.

    Table view of the same data as the graph, with no JavaScript: rows are the
    Acceptance Criteria (grouped under their User Story), columns are the Test
    Cases of the node, and each cell tells whether that criterion is verified by
    that test case. All coverage flags, counts and edit URLs are computed here so
    the template only unpacks plain objects with ``{% for %}`` / ``{% if %}``.

    Args:
        request: The incoming HTTP request.
        node_id: Primary key of the ``FlowNode`` to visualise.

    Returns:
        An ``HttpResponse`` rendering the RTM page.
    """
    flow_node = get_object_or_404(
        FlowNode.objects.select_related('application_map'),
        pk=node_id,
    )

    user_stories = list(
        flow_node.user_stories
        .prefetch_related('criteria__test_cases')
        .order_by('code')
    )

    # Columns: every distinct Test Case that verifies a criterion of this node,
    # ordered by code so the header stays stable between page loads.
    test_cases = list(
        TestCase.objects
        .filter(criteria__user_story__flow_node=flow_node)
        .distinct()
        .order_by('test_code')
    )

    # Rows: one per Acceptance Criterion, grouped under its User Story. Each row
    # carries a boolean cell per column (covered/not) built from the M2M link.
    matrix_groups = []
    ac_count = 0
    covered_count = 0
    for story in user_stories:
        rows = []
        for criterion in story.criteria.all():
            ac_count += 1
            linked_tc_ids = {tc.pk for tc in criterion.test_cases.all()}
            covered = bool(linked_tc_ids)
            if covered:
                covered_count += 1
            rows.append({
                'criterion': criterion,
                'covered': covered,
                # One cell per Test Case column: True where the link exists.
                'cells': [tc.pk in linked_tc_ids for tc in test_cases],
            })
        matrix_groups.append({'user_story': story, 'rows': rows})

    context = {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        # Column headers (real Test Case objects) and grouped AC rows.
        'test_cases': test_cases,
        'matrix_groups': matrix_groups,
        # Stats bar, mirroring the graph view.
        'us_count': len(user_stories),
        'ac_count': ac_count,
        'tc_count': len(test_cases),
        'covered_count': covered_count,
        'uncovered_count': ac_count - covered_count,
    }
    return render(request, 'testcanvas/flow_node_traceability_matrix.html', context)


@login_required
def user_story_detail(request, pk):
    """Render a User Story detail card as an HTMX partial.

    Read-only card reused by both traceability views (graph and RTM table): it
    shows the full Agile narrative and links to the existing edit form. All data
    is shaped here so the template only unpacks a real object.

    Args:
        request: The incoming HTTP request (typically an hx-get).
        pk: Primary key of the ``UserStory`` to display.

    Returns:
        An ``HttpResponse`` rendering the User Story detail partial.
    """
    user_story = get_object_or_404(
        UserStory.objects.select_related('flow_node'), pk=pk,
    )
    return render(request, 'testcanvas/details/_user_story_detail.html', {
        'user_story': user_story,
    })


@login_required
def acceptance_criterion_detail(request, pk):
    """Render an Acceptance Criterion detail card as an HTMX partial.

    Reused by both traceability views. The coverage flag is computed here so the
    template stays a plain, logic-free card.

    Args:
        request: The incoming HTTP request (typically an hx-get).
        pk: Primary key of the ``AcceptanceCriterion`` to display.

    Returns:
        An ``HttpResponse`` rendering the Acceptance Criterion detail partial.
    """
    criterion = get_object_or_404(
        AcceptanceCriterion.objects
        .select_related('user_story')
        .prefetch_related('test_cases'),
        pk=pk,
    )
    return render(request, 'testcanvas/details/_acceptance_criterion_detail.html', {
        'criterion': criterion,
        # Precomputed so the template does not query the M2M itself.
        'covered': criterion.test_cases.exists(),
    })


@login_required
def test_case_detail(request, pk):
    """Render a Test Case detail card as an HTMX partial.

    Reused by both traceability views: shows the full test case (steps, expected
    result, verified criteria) and links to the existing edit form.

    Args:
        request: The incoming HTTP request (typically an hx-get).
        pk: Primary key of the ``TestCase`` to display.

    Returns:
        An ``HttpResponse`` rendering the Test Case detail partial.
    """
    test_case = get_object_or_404(
        TestCase.objects.prefetch_related('criteria'), pk=pk,
    )
    return render(request, 'testcanvas/details/_test_case_detail.html', {
        'test_case': test_case,
    })


@require_POST
@login_required
def set_traceability_view(request):
    """Persist the user's preferred traceability view (graph or matrix).

    Single control point for the whole app: the choice is stored in the session
    so that every "Back to traceability" link and node entry point resolves to
    the same view until the user changes it again (see the ``traceability_view``
    context processor).

    Args:
        request: The incoming HTTP request (POST only).

    Returns:
        A redirect back to the page the toggle was pressed on (``next``), or the
        flow list as a safe fallback.
    """
    mode = request.POST.get('mode')
    if mode in TRACEABILITY_URL_NAMES:
        request.session[TRACEABILITY_SESSION_KEY] = mode
        messages.success(
            request,
            f"Traceability view set to {'matrix' if mode == 'matrix' else 'graph'}.",
        )

    # Redirect back where the toggle was pressed; fall back to the flow list.
    return redirect(request.POST.get('next') or 'testcanvas:map_list')

@login_required
def map_list(request):
    """List every ApplicationMap and allow the creation of a new one.

    Each map is prefetched with its ``referencing_nodes`` so the template can
    tell whether it is used as a sub-flow (and therefore show the
    "Info subflow use" button).
    """
    maps = (
        ApplicationMap.objects
        .order_by('-created_at')
        .prefetch_related('referencing_nodes')
    )
    return render(request, 'testcanvas/map_list.html', {'maps': maps})


@login_required
def map_subflow_usage(request, pk):
    """Return the sub-flow usage list for a map as an HTMX partial.

    Lists each ``FlowNode`` that references this map through ``sub_flow``,
    together with a link to open the containing flow's editor. The response is a
    fragment (``_map_subflow_usage.html``) meant to be swapped into the
    map_list sidebar by HTMX.

    Args:
        request: The HTTP request (typically an hx-get).
        pk: Primary key of the ApplicationMap used as a sub-flow.

    Returns:
        The rendered sidebar partial.
    """
    application_map = get_object_or_404(ApplicationMap, pk=pk)

    # Nodes (in other maps) that reference this map as their sub-flow.
    referencing_nodes = (
        application_map.referencing_nodes
        .select_related('application_map')
        .order_by('application_map__name', 'local_graph_id')
    )

    return render(request, 'testcanvas/_map_subflow_usage.html', {
        'application_map': application_map,
        'referencing_nodes': referencing_nodes,
    })

@require_POST
@login_required
def map_create(request):
    """Create a new (empty) ApplicationMap and jump straight into the editor."""
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, "The flow name cannot be empty.")
        return redirect('testcanvas:map_list')

    application_map = ApplicationMap.objects.create(name=name)
    messages.success(request, f"Flow '{name}' created.")
    return redirect('testcanvas:map_editor', pk=application_map.pk)

@login_required
def map_editor(request, pk):
    """Render the Cytoscape.js editor for a given ApplicationMap."""
    application_map = get_object_or_404(ApplicationMap, pk=pk)

    # graph_data is already stored in Cytoscape format; hand it to the template as JSON.
    graph_data = application_map.graph_data or {}

    # Maps that can be referenced as a sub-flow by a node of THIS map. We only
    # offer other maps; the single-level nesting / cycle rules are enforced by
    # FlowNode.clean() on save.
    subflows = [
        {'id': m.pk, 'name': m.name}
        for m in ApplicationMap.objects.exclude(pk=application_map.pk).order_by('name')
    ]

    # Compact, globally unique node identifiers keyed by their Cytoscape id
    # (local_graph_id). The graph itself only stores local_graph_id, so we hand
    # the front-end this mapping to display each node's stable node_uid.
    node_uids = {
        fn.local_graph_id: fn.node_uid
        for fn in application_map.relational_nodes.all()
    }

    context = {
        'application_map': application_map,
        'graph_data_json': json.dumps(graph_data),
        'subflows_json': json.dumps(subflows),
        'node_uids_json': json.dumps(node_uids),
    }
    return render(request, 'testcanvas/map_editor.html', context)

@require_POST
@login_required
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

    # Persist the rich-text description (Quill HTML) when provided.
    if 'description' in payload:
        application_map.description = payload.get('description') or ''

    # Save the graph and mirror the per-node type / sub-flow reference onto the
    # relational FlowNode rows. Wrapped in a transaction so a validation error
    # (e.g. a cycle or illegal nesting) rolls back the whole save.
    try:
        with transaction.atomic():
            application_map.save()  # sync_flow_nodes() (re)creates FlowNode rows
            _apply_node_types(application_map, norm_nodes)
    except ValidationError as exc:
        return JsonResponse({'ok': False, 'error': '; '.join(exc.messages)}, status=400)

    return JsonResponse({
        'ok': True,
        'graph_data': application_map.graph_data,
        'name': application_map.name,
    })


def _apply_node_types(application_map, norm_nodes):
    """Mirror ``node_type``/``sub_flow`` from graph nodes onto the FlowNode rows.

    ``sync_flow_nodes`` only mirrors title/description, so the node nature is
    applied here from the ``node.data`` payload and validated through
    ``FlowNode.full_clean`` (which enforces the pure/reference invariants).

    Args:
        application_map: The map whose FlowNode rows should be updated.
        norm_nodes: The normalised graph nodes (``[{'data': {...}}, ...]``).

    Raises:
        ValidationError: If any node violates the FlowNode invariants.
    """
    flow_by_id = {
        fn.local_graph_id: fn
        for fn in application_map.relational_nodes.all()
    }
    for node in norm_nodes:
        data = node['data']
        flow_node = flow_by_id.get(str(data.get('id')))
        if flow_node is None:
            continue

        node_type = data.get('node_type') or FlowNode.PURE
        sub_flow_id = data.get('sub_flow') if node_type == FlowNode.SUBFLOW else None

        flow_node.node_type = node_type
        flow_node.sub_flow_id = sub_flow_id or None
        # full_clean runs FlowNode.clean(): coherence, self-reference, single-level
        # nesting and cycle checks. Any problem aborts the surrounding transaction.
        flow_node.full_clean()
        flow_node.save(update_fields=['node_type', 'sub_flow'])

@login_required
def node_user_stories(request, pk, node_id):
    """HTMX endpoint: render the UserStories linked to a graph node (via FlowNode) as an HTML partial."""
    application_map = get_object_or_404(ApplicationMap, pk=pk)
    flow_node = application_map.relational_nodes.filter(local_graph_id=str(node_id)).first()

    # Sub-flow reference nodes delegate testing to another map, so they never own
    # User Stories: show a dedicated notice instead of the (empty) list.
    is_subflow = bool(flow_node and flow_node.node_type == FlowNode.SUBFLOW)
    user_stories = [] if is_subflow else (flow_node.user_stories.all() if flow_node else [])

    return render(request, 'testcanvas/_user_stories.html', {
        'flow_node': flow_node,
        'node_id': node_id,
        'user_stories': user_stories,
        'is_subflow': is_subflow,
    })

@require_POST
@login_required
def map_delete(request, pk):
    """Delete an ApplicationMap, unless it is referenced as a sub-flow.

    A map used as a sub-flow by one or more ``FlowNode`` instances must not be
    deleted: doing so would leave those nodes as orphan references. In that case
    the deletion is blocked and the user is told exactly which maps/nodes still
    reference it, so the references can be removed first.

    Args:
        request: The HTTP request (POST only).
        pk: Primary key of the ApplicationMap to delete.

    Returns:
        An HTTP redirect back to the flow list.
    """
    application_map = get_object_or_404(ApplicationMap, pk=pk)
    name = application_map.name

    # Nodes (in other maps) that reference this map as their sub-flow.
    referencing_nodes = (
        application_map.referencing_nodes
        .select_related('application_map')
        .all()
    )

    if referencing_nodes:
        # Build a human-readable list of "MapName (nodeId — nodeTitle)" usages
        # so the user knows exactly where the sub-flow is still in use.
        usages = ", ".join(
            f"{node.application_map.name} ({node.local_graph_id} — {node.title})"
            for node in referencing_nodes
        )
        messages.error(
            request,
            f"Flow '{name}' cannot be deleted: it is used as a sub-flow by: "
            f"{usages}. Remove these sub-flow references first.",
        )
        return redirect('testcanvas:map_list')

    application_map.delete()
    messages.success(request, f"Flow '{name}' deleted.")
    return redirect('testcanvas:map_list')


# --------------------------------------------------------------------------- #
# ApplicationMapsCollection management (logical grouping layer)
# --------------------------------------------------------------------------- #

@login_required
def collection_list(request):
    """List every ApplicationMapsCollection with its member maps.

    Read-only overview page: each collection is shown together with the maps
    it groups and links to add / edit / delete collections.

    Args:
        request: The incoming HTTP request.

    Returns:
        An ``HttpResponse`` rendering the collections list.
    """
    collections = (
        ApplicationMapsCollection.objects
        .order_by('title')
        .prefetch_related('maps')
    )
    return render(request, 'testcanvas/collection_list.html', {
        'collections': collections,
    })


@login_required
def collection_create(request):
    """Create a new ApplicationMapsCollection.

    GET renders an empty form, POST validates it and creates the collection.

    Args:
        request: The incoming HTTP request.

    Returns:
        An ``HttpResponse`` rendering the form, or a redirect to the list on
        success.
    """
    if request.method == 'POST':
        form = ApplicationMapsCollectionForm(request.POST)
        if form.is_valid():
            collection = form.save()
            messages.success(request, f"Collection '{collection.title}' created.")
            return redirect('testcanvas:collection_list')
    else:
        form = ApplicationMapsCollectionForm()

    return render(request, 'testcanvas/collection_form.html', {
        'form': form,
        'is_edit': False,
    })


@login_required
def collection_edit(request, pk):
    """Edit an existing ApplicationMapsCollection.

    Args:
        request: The incoming HTTP request.
        pk: Primary key of the collection to edit.

    Returns:
        An ``HttpResponse`` rendering the form, or a redirect to the list on
        success.
    """
    collection = get_object_or_404(ApplicationMapsCollection, pk=pk)

    if request.method == 'POST':
        form = ApplicationMapsCollectionForm(request.POST, instance=collection)
        if form.is_valid():
            form.save()
            messages.success(request, f"Collection '{collection.title}' updated.")
            return redirect('testcanvas:collection_list')
    else:
        form = ApplicationMapsCollectionForm(instance=collection)

    return render(request, 'testcanvas/collection_form.html', {
        'form': form,
        'collection': collection,
        'is_edit': True,
    })


@require_POST
@login_required
def collection_delete(request, pk):
    """Delete an ApplicationMapsCollection.

    Deleting a collection only removes the grouping: its maps survive and become
    ungrouped (the FK uses ``SET_NULL``).

    Args:
        request: The incoming HTTP request (POST only).
        pk: Primary key of the collection to delete.

    Returns:
        A redirect back to the collections list.
    """
    collection = get_object_or_404(ApplicationMapsCollection, pk=pk)
    title = collection.title
    collection.delete()
    messages.success(request, f"Collection '{title}' deleted.")
    return redirect('testcanvas:collection_list')


