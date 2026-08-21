import json

import networkx as nx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from testcanvas.models import AcceptanceCriterion, ApplicationMap, ApplicationMapsCollection, FlowNode, UserStory, TestCase
from testcanvas.forms import AcceptanceCriterionForm, ApplicationMapsCollectionForm, UserStoryForm, TestCaseForm
from testcanvas.context_processors import TRACEABILITY_SESSION_KEY, TRACEABILITY_URL_NAMES
from testcanvas.plugins import collect_object_widgets


DEFAULT_LOGIN_LOGO_STATIC_PATH = 'images/white_small_logo_trasparent.png'


def _resolve_login_logo_url() -> str:
    """Return the login logo URL from settings with safe fallback behavior.

    ``LOGIN_PAGE_LOGO_PATH`` can be configured as an external URL, an absolute
    path, or a static-relative path. Empty values fall back to the default
    bundled logo so the login page always renders a valid image.

    Returns:
        The final URL that the login page should use for the logo image.
    """
    configured_path = (getattr(settings, 'LOGIN_PAGE_LOGO_PATH', '') or '').strip()
    if not configured_path:
        return static(DEFAULT_LOGIN_LOGO_STATIC_PATH)

    if configured_path.startswith(('http://', 'https://', '/')):
        return configured_path

    return static(configured_path)


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
            messages.success(request, _("Welcome back, %(username)s!") % {"username": form.get_user().username})
            return redirect('testcanvas:map_list')
    else:
        form = AuthenticationForm(request)

    return render(request, 'testcanvas/index.html', {
        'form': form,
        'login_logo_url': _resolve_login_logo_url(),
    })

@require_POST
def logout_view(request):
    """Log the current user out and return to the login page.

    Args:
        request: The incoming HTTP request (POST only, for CSRF safety).

    Returns:
        A redirect to the login page.
    """
    auth_logout(request)
    messages.info(request, _("You have been logged out."))
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
            messages.success(request, _("User Story '%(code)s' created.") % {"code": user_story.code})
            return redirect('testcanvas:user_story_manage', node_id=flow_node.pk)
    else:
        form = UserStoryForm()

    user_stories = flow_node.user_stories.order_by('code')
    return render(request, 'testcanvas/user_story_manage.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_stories': user_stories,
        'form': form,
        # Plugin extension slot for this flow node (see flow_node_traceability).
        'plugin_widgets': collect_object_widgets('flow_node', flow_node, request),
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
            messages.success(request, _("User Story '%(code)s' updated.") % {"code": user_story.code})
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
    messages.success(request, _("User Story '%(code)s' deleted.") % {"code": code})
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
            messages.success(request, _("Acceptance Criterion '%(code)s' created.") % {"code": criterion.code})
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
        # Plugin extension slot for this user story (e.g. links to test cases
        # verifying its acceptance criteria). Empty when no plugin is installed.
        'plugin_widgets': collect_object_widgets('user_story', user_story, request),
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
            messages.success(request, _("Acceptance Criterion '%(code)s' updated.") % {"code": criterion.code})
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
    messages.success(request, _("Acceptance Criterion '%(code)s' deleted.") % {"code": code})
    return redirect('testcanvas:acceptance_criterion_manage', user_story_id=user_story.pk)

@login_required
def test_case_manage(request, acceptance_criterion_id):
    """List and create TestCases for a given AcceptanceCriterion.

    Standard Django view: GET renders the list plus an empty create form,
    POST validates the form and creates a new TestCase bound to the criterion.
    Mirrors ``acceptance_criterion_manage``.
    """
    criterion = get_object_or_404(
        AcceptanceCriterion.objects.select_related('user_story__flow_node__application_map'),
        pk=acceptance_criterion_id,
    )
    user_story = criterion.user_story
    flow_node = user_story.flow_node

    if request.method == 'POST':
        form = TestCaseForm(request.POST)
        if form.is_valid():
            test_case = form.save(commit=False)
            test_case.acceptance_criterion = criterion
            test_case.save()
            messages.success(request, _("Test Case '%(code)s' created.") % {"code": test_case.code})
            return redirect('testcanvas:test_case_manage', acceptance_criterion_id=criterion.pk)
    else:
        form = TestCaseForm()

    test_cases = criterion.test_cases.order_by('code')
    return render(request, 'testcanvas/test_case_manage.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'criterion': criterion,
        'test_cases': test_cases,
        'form': form,
    })

@login_required
def test_case_edit(request, pk):
    """Edit an existing TestCase following the AcceptanceCriterion edit pattern."""
    test_case = get_object_or_404(
        TestCase.objects.select_related('acceptance_criterion__user_story__flow_node__application_map'),
        pk=pk,
    )
    criterion = test_case.acceptance_criterion
    user_story = criterion.user_story
    flow_node = user_story.flow_node

    if request.method == 'POST':
        form = TestCaseForm(request.POST, instance=test_case)
        if form.is_valid():
            form.save()
            messages.success(request, _("Test Case '%(code)s' updated.") % {"code": test_case.code})
            return redirect('testcanvas:test_case_manage', acceptance_criterion_id=criterion.pk)
    else:
        form = TestCaseForm(instance=test_case)

    return render(request, 'testcanvas/test_case_edit.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'criterion': criterion,
        'test_case': test_case,
        'form': form,
    })

@require_POST
@login_required
def test_case_delete(request, pk):
    """Delete a TestCase, returning to its Acceptance Criterion manage page."""
    test_case = get_object_or_404(
        TestCase.objects.select_related('acceptance_criterion'),
        pk=pk,
    )
    criterion = test_case.acceptance_criterion
    code = test_case.code
    test_case.delete()
    messages.success(request, _("Test Case '%(code)s' deleted.") % {"code": code})
    return redirect('testcanvas:test_case_manage', acceptance_criterion_id=criterion.pk)

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
def flow_node_traceability(request, node_id):
    """Render the ISTQB traceability graph for a single FlowNode.

    Visualises the complete ``UserStory -> AcceptanceCriterion -> TestCase``
    decomposition (test basis + test cases) with Cytoscape.js. All data
    shaping happens here: the view emits a ready-to-use Cytoscape ``elements``
    list (nodes + edges) with every display value and edit URL already baked
    into each node's ``data``. The front-end only feeds this list to Cytoscape
    and lays it out, so the JS stays thin.

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
    seen_ac = set()       # criterion.pk already added as a node (dedup across stories)
    seen_tc = set()       # test_case.pk already added as a node (dedup across criteria)

    for story in user_stories:
        us_id = f"US_{story.pk}"
        criteria = list(story.criteria.all())
        # US is complete if it has AC and all AC are covered by TC.
        us_complete = len(criteria) > 0 and all(c.test_cases.exists() for c in criteria)
        
        # Only the data Cytoscape needs to draw and identify the node is sent.
        # The full detail (Agile fields, edit link, etc.) is fetched on demand
        # from the shared HTMX detail partial via ``detail_url``.
        nodes.append({'data': {
            'id': us_id,
            'label': story.code,
            'type': 'us',
            'code': story.code,
            'is_complete': str(us_complete).lower(),
            # URL of the HTMX detail card opened when the node is tapped.
            'detail_url': reverse('testcanvas:user_story_detail', args=[story.pk]),
        }})

        for criterion in criteria:
            ac_id = f"AC_{criterion.pk}"
            # AC is complete if it has at least one TC.
            ac_complete = criterion.test_cases.exists()

            # A criterion can belong to several stories: add the node once but
            # always draw the US -> AC decomposition edge.
            if criterion.pk not in seen_ac:
                seen_ac.add(criterion.pk)
                nodes.append({'data': {
                    'id': ac_id,
                    'label': criterion.code,
                    'type': 'ac',
                    'code': criterion.code,
                    'is_complete': str(ac_complete).lower(),
                    'detail_url': reverse('testcanvas:acceptance_criterion_detail', args=[criterion.pk]),
                }})
            edges.append({'data': {'id': f"e_{us_id}_{ac_id}", 'source': us_id, 'target': ac_id, 'kind': 'decompose'}})

            # Test Cases hang off their Acceptance Criterion (AC -> TC). Each
            # criterion is added once (dedup) but the verification edge is always
            # drawn so the AC -> TC decomposition stays visible.
            for test_case in criterion.test_cases.all():
                tc_id = f"TC_{test_case.pk}"
                if test_case.pk not in seen_tc:
                    seen_tc.add(test_case.pk)
                    nodes.append({'data': {
                        'id': tc_id,
                        'label': test_case.code,
                        'type': 'tc',
                        'code': test_case.code,
                        'is_complete': 'true',
                        'detail_url': reverse('testcanvas:test_case_detail', args=[test_case.pk]),
                    }})
                edges.append({'data': {'id': f"e_{ac_id}_{tc_id}", 'source': ac_id, 'target': tc_id, 'kind': 'verify'}})

    # --- Counters, computed server-side so the template (not JS) renders the
    # stats bar and the lane button states. ---
    us_count = len(user_stories)
    ac_count = len(seen_ac)
    tc_count = len(seen_tc)

    context = {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        # Ready-to-use Cytoscape elements: the JS feeds this straight in.
        'elements_json': json.dumps(nodes + edges),
        'us_count': us_count,
        'ac_count': ac_count,
        'tc_count': tc_count,
        # Plugin extension slot: widgets (progress, buttons, dividers, …) that
        # installed plugins contribute for this flow node. Empty when no plugin
        # is installed, so the template slot simply renders nothing.
        'plugin_widgets': collect_object_widgets('flow_node', flow_node, request),
    }
    return render(request, 'testcanvas/flow_node_traceability.html', context)

@login_required
def flow_node_traceability_matrix(request, node_id):
    """Render the ISTQB Requirements Traceability Matrix (RTM) for a FlowNode.

    Table view of the complete traceability chain: Acceptance Criteria grouped
    under their User Stories, with Test Cases shown as sub-rows under each AC.
    All counts and edit URLs are computed here so the template only unpacks
    plain objects with ``{% for %}`` / ``{% if %}``.

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

    # Rows: one per Acceptance Criterion, grouped under its User Story.
    matrix_groups = []
    ac_count = 0
    for story in user_stories:
        rows = []
        for criterion in story.criteria.all():
            ac_count += 1
            rows.append({
                'criterion': criterion,
                'test_cases': list(criterion.test_cases.all())
            })
        matrix_groups.append({'user_story': story, 'rows': rows})

    # Count total test cases across all criteria
    tc_count = sum(len(row['test_cases']) for group in matrix_groups for row in group['rows'])

    context = {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        # Grouped AC rows (no Test Case columns in the core).
        'matrix_groups': matrix_groups,
        # Stats bar, mirroring the graph view.
        'us_count': len(user_stories),
        'ac_count': ac_count,
        'tc_count': tc_count,
        # Plugin extension slot: widgets (progress, buttons, dividers, …) that
        # installed plugins contribute for this flow node. Empty when no plugin
        # is installed, so the template slot simply renders nothing.
        'plugin_widgets': collect_object_widgets('flow_node', flow_node, request),
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
        # Plugin extension slot for this user story (e.g. test-case shortcuts
        # or coverage widgets). Empty when no plugin is installed, so the
        # template slot simply renders nothing.
        'plugin_widgets': collect_object_widgets('user_story', user_story, request),
    })

@login_required
def acceptance_criterion_detail(request, pk):
    """Render an Acceptance Criterion detail card as an HTMX partial.

    Reused by both traceability views. The card is a plain, logic-free view of
    the criterion (test coverage is a plugin concern and is not shown here).

    Args:
        request: The incoming HTTP request (typically an hx-get).
        pk: Primary key of the ``AcceptanceCriterion`` to display.

    Returns:
        An ``HttpResponse`` rendering the Acceptance Criterion detail partial.
    """
    criterion = get_object_or_404(
        AcceptanceCriterion.objects.select_related('user_story'),
        pk=pk,
    )
    return render(request, 'testcanvas/details/_acceptance_criterion_detail.html', {
        'criterion': criterion,
        # Plugin extension slot for this acceptance criterion (e.g. links to
        # the test cases that verify it, or a coverage widget). Empty when no
        # plugin is installed, so the template slot simply renders nothing.
        'plugin_widgets': collect_object_widgets('acceptance_criterion', criterion, request),
    })

@login_required
def test_case_detail(request, pk):
    """Render a Test Case detail card as an HTMX partial.

    Displayed in the shared detail sidebar when a test case node is tapped in
    the traceability graph or clicked in the matrix. Shows the test case
    description and its owning Acceptance Criterion.

    Args:
        request: The incoming HTTP request (typically an hx-get).
        pk: Primary key of the ``TestCase`` to display.

    Returns:
        An ``HttpResponse`` rendering the Test Case detail partial.
    """
    test_case = get_object_or_404(
        TestCase.objects.select_related('acceptance_criterion'),
        pk=pk,
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
        messages.error(request, _("The flow name cannot be empty."))
        return redirect('testcanvas:map_list')

    application_map = ApplicationMap.objects.create(name=name)
    messages.success(request, _("Flow '%(name)s' created.") % {"name": name})
    return redirect('testcanvas:map_editor', pk=application_map.pk)

@login_required
def map_editor_by_uid(request, flow_uid):
    """Resolve a compact flow UID to the canonical PK-based editor URL.

    This endpoint is an ingress route for external callers that only know the
    stable ``flow_uid``. After lookup, it redirects to the existing
    ``map_editor`` route so all internal navigation and JS configuration keep
    using the current PK-based URLs without any further changes.

    Args:
        request: The incoming HTTP request.
        flow_uid: Compact, globally unique flow identifier.

    Returns:
        An HTTP redirect to the canonical ``map_editor`` URL.
    """
    application_map = get_object_or_404(ApplicationMap, flow_uid=flow_uid)
    return redirect('testcanvas:map_editor', pk=application_map.pk)

@login_required
def map_editor(request, pk):
    """Render the Cytoscape.js editor for a given ApplicationMap."""
    application_map = get_object_or_404(ApplicationMap, pk=pk)

    # graph_data is already stored in Cytoscape format; hand it to the template as JSON.
    graph_data = application_map.graph_data or {}

    # Ensure coverage colors are applied to all nodes based on their test basis
    # completeness (US → AC → TC chain). This is also done on save, but we do it
    # here at load time to ensure the UI always shows accurate colors even if the
    # graph was modified externally (e.g., via API) or created without re-saving.
    if graph_data and graph_data.get('elements') and graph_data['elements'].get('nodes'):
        norm_nodes = graph_data['elements']['nodes']
        # Prefetch all related data for efficient coverage calculation.
        flow_by_id = {
            fn.local_graph_id: fn
            for fn in application_map.relational_nodes.prefetch_related(
                'user_stories__criteria__test_cases'
            ).all()
        }
        # Apply coverage colors to each node in the graph.
        for node in norm_nodes:
            data = node.get('data', {})
            node_id = str(data.get('id', ''))
            flow_node = flow_by_id.get(node_id)
            if flow_node:
                data['color'] = get_node_coverage_color(flow_node)

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

    # Collections the map can be attached to. Passed as real objects so the
    # header <select> is rendered server-side (the current one pre-selected),
    # letting the user (re)group this map on the next Save.
    collections = ApplicationMapsCollection.objects.all()

    context = {
        'application_map': application_map,
        'graph_data_json': json.dumps(graph_data),
        'subflows_json': json.dumps(subflows),
        'node_uids_json': json.dumps(node_uids),
        'collections': collections,
        # Plugin extension slot for the whole map (e.g. aggregate coverage).
        # Empty when no plugin is installed, so the header slot renders nothing.
        'plugin_widgets': collect_object_widgets('application_map', application_map, request),
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

    # (Re)group the map under a collection chosen in the editor header. An empty
    # value detaches the map (SET_NULL); an unknown/invalid id fails silently to
    # None ("— No collection —") so a stale option can never break the save.
    if 'collection' in payload:
        collection_id = payload.get('collection') or None
        if collection_id is None:
            application_map.collection = None
        else:
            application_map.collection = (
                ApplicationMapsCollection.objects.filter(pk=collection_id).first()
            )

    # Save the graph and mirror the per-node type / sub-flow reference onto the
    # relational FlowNode rows. Wrapped in a transaction so a validation error
    # (e.g. a cycle or illegal nesting) rolls back the whole save.
    try:
        with transaction.atomic():
            application_map.save()  # sync_flow_nodes() (re)creates FlowNode rows
            _apply_node_types(application_map, norm_nodes)
            # Apply coverage colors: green if complete, yellow if incomplete.
            _apply_coverage_colors(application_map, norm_nodes)
            # Save again with updated colors.
            application_map.save()
    except ValidationError as exc:
        return JsonResponse({'ok': False, 'error': '; '.join(exc.messages)}, status=400)

    return JsonResponse({
        'ok': True,
        'graph_data': application_map.graph_data,
        'name': application_map.name,
    })

def get_node_coverage_color(flow_node):
    """Calculate the coverage color for a FlowNode.

    Returns green (#10b981) if all UserStories have complete AcceptanceCriteria
    coverage (each AC has at least one TestCase), or yellow (#fbbf24) if any
    AC lacks a TestCase or if any UserStory lacks an AC.

    Args:
        flow_node: The ``FlowNode`` whose coverage should be evaluated.

    Returns:
        A color code (hex string) representing the coverage status.
    """
    # Iterate through all user stories linked to this node.
    for user_story in flow_node.user_stories.all():
        criteria = list(user_story.criteria.all())
        # US must have at least one AC; if it has none, it's incomplete.
        if not criteria:
            return '#fbbf24'  # yellow
        # All AC must have at least one TC; if any lacks a TC, it's incomplete.
        for criterion in criteria:
            if not criterion.test_cases.exists():
                return '#fbbf24'  # yellow
    
    # All US have AC, and all AC have TC: complete coverage.
    return '#10b981'  # green


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


def _apply_coverage_colors(application_map, norm_nodes):
    """Apply coverage colors to nodes based on their test basis completeness.

    A node is colored green (#10b981) if all its UserStories have complete
    AcceptanceCriteria coverage (all AC have TestCases), or yellow (#fbbf24)
    if coverage is incomplete or missing.

    Args:
        application_map: The map whose nodes should be colored.
        norm_nodes: The normalised graph nodes (``[{'data': {...}}, ...]``).
    """
    # Prefetch all related data (US → AC → TC) for efficient coverage calculation.
    flow_by_id = {
        fn.local_graph_id: fn
        for fn in application_map.relational_nodes.prefetch_related(
            'user_stories__criteria__test_cases'
        ).all()
    }
    
    for node in norm_nodes:
        data = node['data']
        node_id = str(data.get('id'))
        flow_node = flow_by_id.get(node_id)
        
        if flow_node is None:
            # Node not yet synchronized to FlowNode table; skip color update.
            continue
        
        # Calculate and apply the coverage color based on test case completeness.
        # Yellow if any AC lacks a TC or any US lacks an AC; green otherwise.
        data['color'] = get_node_coverage_color(flow_node)
    
    # Persist the updated graph with new colors.
    application_map.graph_data = {
        'data': application_map.graph_data.get('data', []),
        'directed': True,
        'multigraph': False,
        'elements': {'nodes': norm_nodes, 'edges': application_map.graph_data.get('elements', {}).get('edges', [])},
    }

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

    # Nodes (in other maps) that reference this map as a sub-flow.
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
            _(
                "Flow '%(name)s' cannot be deleted: it is used as a sub-flow by: "
                "%(usages)s. Remove these sub-flow references first."
            ) % {"name": name, "usages": usages},
        )
        return redirect('testcanvas:map_list')

    application_map.delete()
    messages.success(request, _("Flow '%(name)s' deleted.") % {"name": name})
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
    The ``next`` target (list or tree view) is preserved so the user returns to
    the page they came from, both on save and on cancel.

    Args:
        request: The incoming HTTP request.

    Returns:
        An ``HttpResponse`` rendering the form, or a redirect to ``next`` on
        success.
    """
    # Where to go back after save/cancel; falls back to the flat list view.
    next_url = (
        request.POST.get('next')
        or request.GET.get('next')
        or reverse('testcanvas:collection_list')
    )

    if request.method == 'POST':
        form = ApplicationMapsCollectionForm(request.POST)
        if form.is_valid():
            collection = form.save()
            messages.success(request, _("Collection '%(title)s' created.") % {"title": collection.title})
            return redirect(next_url)
    else:
        form = ApplicationMapsCollectionForm()

    return render(request, 'testcanvas/collection_form.html', {
        'form': form,
        'is_edit': False,
        'next_url': next_url,
    })

@login_required
def collection_edit(request, pk):
    """Edit an existing ApplicationMapsCollection.

    The ``next`` target (list or tree view) is preserved so the user returns to
    the page they came from, both on save and on cancel.

    Args:
        request: The incoming HTTP request.
        pk: Primary key of the collection to edit.

    Returns:
        An ``HttpResponse`` rendering the form, or a redirect to ``next`` on
        success.
    """
    collection = get_object_or_404(ApplicationMapsCollection, pk=pk)

    # Where to go back after save/cancel; falls back to the flat list view.
    next_url = (
        request.POST.get('next')
        or request.GET.get('next')
        or reverse('testcanvas:collection_list')
    )

    if request.method == 'POST':
        form = ApplicationMapsCollectionForm(request.POST, instance=collection)
        if form.is_valid():
            form.save()
            messages.success(request, _("Collection '%(title)s' updated.") % {"title": collection.title})
            return redirect(next_url)
    else:
        form = ApplicationMapsCollectionForm(instance=collection)

    return render(request, 'testcanvas/collection_form.html', {
        'form': form,
        'collection': collection,
        'is_edit': True,
        'next_url': next_url,
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
    messages.success(request, _("Collection '%(title)s' deleted.") % {"title": title})
    return redirect('testcanvas:collection_list')

