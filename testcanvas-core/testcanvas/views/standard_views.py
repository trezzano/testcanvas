import json

import networkx as nx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from testcanvas.models import AcceptanceCriterion, ApplicationMap, ApplicationMapsCollection, FlowNode, UserStory, TestCase
from testcanvas.forms import AcceptanceCriterionForm, ApplicationMapsCollectionForm, UserStoryForm, TestCaseForm
from testcanvas.context_processors import (
    DEFAULT_TRACEABILITY_MODE,
    TRACEABILITY_SESSION_KEY,
    TRACEABILITY_URL_NAMES,
)
from testcanvas.plugins import collect_object_widgets
from testcanvas.services import (
    BusinessRuleViolation,
    MapInUseAsSubflow,
    create_acceptance_criteria,
    create_application_map,
    create_test_cases,
    create_user_stories,
    delete_artefact,
    update_application_map,
    update_artefact,
)
from testcanvas.utilities.optional_fields import resolve_project_for
from testcanvas.utilities.permissions import (
    AccessDenied,
    can_write,
    clear_access_cache,
    filter_collections,
    filter_maps,
    get_access,
    is_unrestricted,
)
from testcanvas.views._permissions import ensure_can_read, ensure_can_write, get_object_by_uid_or_404
from testcanvas.utilities.other_support import check_acceptance_criteria_coverage


def _add_service_errors(form, exc: ValidationError) -> None:
    """Attach a service ``ValidationError`` to a bound form.

    Field errors are attached to the matching form field when it exists,
    everything else becomes a non-field error, so the template can render
    them like regular form errors.

    Args:
        form: The bound form being processed.
        exc: The error raised by a domain service.
    """
    if hasattr(exc, 'error_dict'):
        for field, errors in exc.message_dict.items():
            form.add_error(field if field in form.fields else None, errors)
    else:
        form.add_error(None, exc.messages)


def _create_from_form(request, form, create_service, parent):
    """Create one artefact from a valid form through a domain service.

    Args:
        request: The incoming HTTP request (provides the acting user).
        form: A valid ModelForm whose ``cleaned_data`` holds the new values.
        create_service: One of the bulk ``create_*`` services.
        parent: The parent artefact passed to the service.

    Returns:
        The created instance, or ``None`` when the service rejected the data
        (errors are then attached to ``form``).
    """
    try:
        return create_service(request.user, parent, [dict(form.cleaned_data)])[0]
    except ValidationError as exc:
        _add_service_errors(form, exc)
    except BusinessRuleViolation as exc:
        form.add_error(None, str(exc))
    return None


def _update_from_form(request, form, obj) -> bool:
    """Persist a valid edit form through :func:`update_artefact`.

    Args:
        request: The incoming HTTP request (provides the acting user).
        form: A valid ModelForm bound to ``obj``.
        obj: The artefact being edited.

    Returns:
        ``True`` on success, ``False`` when the service rejected the data
        (errors are then attached to ``form``).
    """
    try:
        # Only the fields rendered by the form may change.
        update_artefact(request.user, obj, dict(form.cleaned_data), set(form.fields))
    except ValidationError as exc:
        _add_service_errors(form, exc)
        return False
    except BusinessRuleViolation as exc:
        form.add_error(None, str(exc))
        return False
    return True


def _ensure_read_or_write(request, obj) -> None:
    """Check read access on GET and write access on any other method.

    Shared by the views that both display an object and save it in place
    (manage/edit/detail pages): reading needs read access, POSTing needs write.

    Args:
        request: The incoming HTTP request.
        obj: A collection or any artefact of the ISTQB chain.

    Raises:
        Http404: If the object is not readable.
        PermissionDenied: If a write is attempted without write access.
    """
    if request.method == 'POST':
        ensure_can_write(request.user, obj)
    else:
        ensure_can_read(request.user, obj)


DEFAULT_LOGIN_LOGO_STATIC_PATH = 'images/test_canvas_logo.svg'


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
    # Reading the list needs read access, creating a story needs write access.
    _ensure_read_or_write(request, flow_node)

    # Optional fields shown depend on global preferences.
    project = resolve_project_for(flow_node)

    if request.method == 'POST':
        form = UserStoryForm(request.POST, project=project)
        if form.is_valid():
            # The service enforces write access and the SUBFLOW rule.
            user_story = _create_from_form(request, form, create_user_stories, flow_node)
            if user_story is not None:
                messages.success(request, _("User Story '%(code)s' created.") % {"code": user_story.code})
                return redirect('testcanvas:user_story_manage', node_id=flow_node.pk)
    else:
        form = UserStoryForm(project=project)

    user_stories = flow_node.user_stories.order_by('code')
    return render(request, 'testcanvas/user_stories/user_stories_manage.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_stories': user_stories,
        'form': form,
        # Hides create/edit/delete controls for read-only users.
        'can_write': can_write(request.user, flow_node),
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
    _ensure_read_or_write(request, flow_node)

    # Optional fields shown depend on global preferences.
    project = resolve_project_for(user_story)

    if request.method == 'POST':
        form = UserStoryForm(request.POST, instance=user_story, project=project)
        if form.is_valid() and _update_from_form(request, form, user_story):
            messages.success(request, _("User Story '%(code)s' updated.") % {"code": user_story.code})
            return redirect('testcanvas:user_story_manage', node_id=flow_node.pk)
    else:
        form = UserStoryForm(instance=user_story, project=project)

    return render(request, 'testcanvas/user_stories/user_stories_edit.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_story': user_story,
        'form': form,
        'can_write': can_write(request.user, flow_node),
    })

@require_POST
@login_required
def user_story_delete(request, node_id, pk):
    """Delete a UserStory belonging to the given FlowNode."""
    flow_node = get_object_or_404(FlowNode.objects.select_related('application_map'), pk=node_id)
    user_story = get_object_or_404(UserStory, pk=pk, flow_node=flow_node)
    ensure_can_write(request.user, flow_node)
    code = user_story.code
    delete_artefact(request.user, user_story)
    messages.success(request, _("User Story '%(code)s' deleted.") % {"code": code})
    # Back to the node's traceability, in whichever view the user prefers.
    return redirect('testcanvas:flow_node_traceability_go', node_id=flow_node.pk)

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
    _ensure_read_or_write(request, flow_node)

    # Optional fields shown depend on global preferences.
    project = resolve_project_for(user_story)

    if request.method == 'POST':
        form = AcceptanceCriterionForm(request.POST, project=project)
        if form.is_valid():
            criterion = _create_from_form(request, form, create_acceptance_criteria, user_story)
            if criterion is not None:
                messages.success(request, _("Acceptance Criterion '%(code)s' created.") % {"code": criterion.code})
                return redirect('testcanvas:acceptance_criterion_manage', user_story_id=user_story.pk)
    else:
        form = AcceptanceCriterionForm(project=project)

    criteria = user_story.criteria.order_by('code')
    return render(request, 'testcanvas/acceptance_criteria/acceptance_criteria_manage.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_story': user_story,
        'criteria': criteria,
        'form': form,
        'can_write': can_write(request.user, flow_node),
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
    _ensure_read_or_write(request, flow_node)

    # Optional fields shown depend on global preferences.
    project = resolve_project_for(criterion)

    if request.method == 'POST':
        form = AcceptanceCriterionForm(request.POST, instance=criterion, project=project)
        if form.is_valid() and _update_from_form(request, form, criterion):
            messages.success(request, _("Acceptance Criterion '%(code)s' updated.") % {"code": criterion.code})
            return redirect('testcanvas:acceptance_criterion_manage', user_story_id=user_story.pk)
    else:
        form = AcceptanceCriterionForm(instance=criterion, project=project)

    return render(request, 'testcanvas/acceptance_criteria/acceptance_criteria_edit.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_story': user_story,
        'criterion': criterion,
        'form': form,
        'can_write': can_write(request.user, flow_node),
    })

@require_POST
@login_required
def acceptance_criterion_delete(request, pk):
    """Delete an AcceptanceCriterion, returning to its node's traceability."""
    criterion = get_object_or_404(
        AcceptanceCriterion.objects.select_related('user_story__flow_node__application_map'),
        pk=pk,
    )
    flow_node = criterion.user_story.flow_node
    ensure_can_write(request.user, flow_node)
    code = criterion.code
    delete_artefact(request.user, criterion)
    messages.success(request, _("Acceptance Criterion '%(code)s' deleted.") % {"code": code})
    # Back to the node's traceability, in whichever view the user prefers.
    return redirect('testcanvas:flow_node_traceability_go', node_id=flow_node.pk)

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
    _ensure_read_or_write(request, flow_node)

    # Optional TestCase fields shown depend on global preferences.
    project = resolve_project_for(criterion)

    if request.method == 'POST':
        form = TestCaseForm(request.POST, project=project)
        if form.is_valid():
            test_case = _create_from_form(request, form, create_test_cases, criterion)
            if test_case is not None:
                messages.success(request, _("Test Case '%(code)s' created.") % {"code": test_case.code})
                return redirect('testcanvas:test_case_manage', acceptance_criterion_id=criterion.pk)
    else:
        form = TestCaseForm(project=project)

    test_cases = criterion.test_cases.order_by('code')
    return render(request, 'testcanvas/test_cases/test_cases_manage.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'criterion': criterion,
        'test_cases': test_cases,
        'form': form,
        'can_write': can_write(request.user, flow_node),
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
    _ensure_read_or_write(request, flow_node)

    # Optional TestCase fields shown depend on global preferences.
    project = resolve_project_for(test_case)

    if request.method == 'POST':
        form = TestCaseForm(request.POST, instance=test_case, project=project)
        if form.is_valid() and _update_from_form(request, form, test_case):
            messages.success(request, _("Test Case '%(code)s' updated.") % {"code": test_case.code})
            return redirect('testcanvas:test_case_manage', acceptance_criterion_id=criterion.pk)
    else:
        form = TestCaseForm(instance=test_case, project=project)

    return render(request, 'testcanvas/test_cases/test_cases_edit.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'criterion': criterion,
        'test_case': test_case,
        'form': form,
        'can_write': can_write(request.user, flow_node),
    })

@require_POST
@login_required
def test_case_delete(request, pk):
    """Delete a TestCase, returning to its node's traceability."""
    test_case = get_object_or_404(
        TestCase.objects.select_related(
            'acceptance_criterion__user_story__flow_node__application_map',
        ),
        pk=pk,
    )
    flow_node = test_case.acceptance_criterion.user_story.flow_node
    ensure_can_write(request.user, flow_node)
    code = test_case.code
    delete_artefact(request.user, test_case)
    messages.success(request, _("Test Case '%(code)s' deleted.") % {"code": code})
    # Back to the node's traceability, in whichever view the user prefers.
    return redirect('testcanvas:flow_node_traceability_go', node_id=flow_node.pk)

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
    ensure_can_read(request.user, flow_node)
    user_stories = (
        flow_node.user_stories
        .prefetch_related('criteria')
        .order_by('code')
    )
    return render(request, 'testcanvas/acceptance_criteria/acceptance_criteria_overview.html', {
        'flow_node': flow_node,
        'application_map': flow_node.application_map,
        'user_stories': user_stories,
        'can_write': can_write(request.user, flow_node),
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
    ensure_can_read(request.user, flow_node)

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
        # Transient highlight marker for a UID deep-link (empty = none). It is
        # purely presentational and never persisted; the front-end matches it
        # against a Cytoscape node id (e.g. ``AC_12``). Mirrors ``map_editor``.
        'highlight_node_id': request.GET.get('highlight', ''),
        # Hides the add/edit controls for read-only users.
        'can_write': can_write(request.user, flow_node),
        # Plugin extension slot: widgets (progress, buttons, dividers, …) that
        # installed plugins contribute for this flow node. Empty when no plugin
        # is installed, so the template slot simply renders nothing.
        'plugin_widgets': collect_object_widgets('flow_node', flow_node, request),
    }
    return render(request, 'testcanvas/traceability/traceability_flow_node.html', context)

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
    ensure_can_read(request.user, flow_node)

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
        'can_write': can_write(request.user, flow_node),
        # Plugin extension slot: widgets (progress, buttons, dividers, …) that
        # installed plugins contribute for this flow node. Empty when no plugin
        # is installed, so the template slot simply renders nothing.
        'plugin_widgets': collect_object_widgets('flow_node', flow_node, request),
    }
    return render(request, 'testcanvas/traceability/traceability_matrix.html', context)

@login_required
def user_story_detail(request, pk):
    """Render a User Story detail card as an editable HTMX partial.

    Editable card reused by both traceability views (graph and RTM table) and by
    the full-page edit template. On GET renders the partial with an unbound
    ``UserStoryForm`` prefilled from the instance; on POST validates the form
    and saves in place, re-rendering the same partial (with a ``saved`` flash
    on success, or field errors on failure). Always returns HTTP 200 so HTMX
    can swap the response into the sidebar.

    Args:
        request: The incoming HTTP request (hx-get on first load, hx-post on
            inline save).
        pk: Primary key of the ``UserStory`` to display or update.

    Returns:
        An ``HttpResponse`` rendering the User Story detail partial.
    """
    user_story = get_object_or_404(
        UserStory.objects.select_related('flow_node__application_map'), pk=pk,
    )
    # GET needs read access, the inline save (POST) needs write access.
    _ensure_read_or_write(request, user_story)

    # POST → save inline; GET → show the current values as an editable form.
    saved = False
    project = resolve_project_for(user_story)
    if request.method == 'POST':
        form = UserStoryForm(request.POST, instance=user_story, project=project)
        if form.is_valid() and _update_from_form(request, form, user_story):
            saved = True
            # Rebuild an unbound form from the freshly-saved instance so the
            # partial re-renders with the canonical values and no "dirty" state.
            form = UserStoryForm(instance=user_story, project=project)
    else:
        form = UserStoryForm(instance=user_story, project=project)

    return render(request, 'testcanvas/user_stories/_user_stories_detail.html', {
        'user_story': user_story,
        'form': form,
        'saved': saved,
        'can_write': can_write(request.user, user_story),
        # Plugin extension slot for this user story (e.g. test-case shortcuts
        # or coverage widgets). Empty when no plugin is installed, so the
        # template slot simply renders nothing.
        'plugin_widgets': collect_object_widgets('user_story', user_story, request),
    })

@login_required
def acceptance_criterion_detail(request, pk):
    """Render an Acceptance Criterion detail card as an editable HTMX partial.

    Reused by both traceability views and by the full-page edit template. On
    GET renders the partial with an unbound ``AcceptanceCriterionForm``
    prefilled from the instance; on POST validates and saves in place,
    re-rendering the same partial (with a ``saved`` flash on success or field
    errors on failure).

    Args:
        request: The incoming HTTP request (hx-get on first load, hx-post on
            inline save).
        pk: Primary key of the ``AcceptanceCriterion`` to display or update.

    Returns:
        An ``HttpResponse`` rendering the Acceptance Criterion detail partial.
    """
    criterion = get_object_or_404(
        AcceptanceCriterion.objects.select_related('user_story__flow_node__application_map'),
        pk=pk,
    )
    _ensure_read_or_write(request, criterion)

    saved = False
    project = resolve_project_for(criterion)
    if request.method == 'POST':
        form = AcceptanceCriterionForm(request.POST, instance=criterion, project=project)
        if form.is_valid() and _update_from_form(request, form, criterion):
            saved = True
            form = AcceptanceCriterionForm(instance=criterion, project=project)
    else:
        form = AcceptanceCriterionForm(instance=criterion, project=project)

    return render(request, 'testcanvas/acceptance_criteria/_acceptance_criteria_detail.html', {
        'criterion': criterion,
        'form': form,
        'saved': saved,
        'can_write': can_write(request.user, criterion),
        # Plugin extension slot for this acceptance criterion (e.g. links to
        # the test cases that verify it, or a coverage widget). Empty when no
        # plugin is installed, so the template slot simply renders nothing.
        'plugin_widgets': collect_object_widgets('acceptance_criterion', criterion, request),
    })

@login_required
def test_case_detail(request, pk):
    """Render a Test Case detail card as an editable HTMX partial.

    Displayed in the shared detail sidebar when a test case node is tapped in
    the traceability graph or clicked in the matrix, and reused by the
    full-page edit template. On GET renders the partial with an unbound
    ``TestCaseForm`` prefilled from the instance; on POST validates and saves
    in place.

    Args:
        request: The incoming HTTP request (hx-get on first load, hx-post on
            inline save).
        pk: Primary key of the ``TestCase`` to display or update.

    Returns:
        An ``HttpResponse`` rendering the Test Case detail partial.
    """
    test_case = get_object_or_404(
        TestCase.objects.select_related('acceptance_criterion__user_story__flow_node__application_map'),
        pk=pk,
    )
    _ensure_read_or_write(request, test_case)

    saved = False
    project = resolve_project_for(test_case)
    if request.method == 'POST':
        form = TestCaseForm(request.POST, instance=test_case, project=project)
        if form.is_valid() and _update_from_form(request, form, test_case):
            saved = True
            form = TestCaseForm(instance=test_case, project=project)
    else:
        form = TestCaseForm(instance=test_case, project=project)

    return render(request, 'testcanvas/test_cases/_test_cases_detail.html', {
        'test_case': test_case,
        'form': form,
        'saved': saved,
        'can_write': can_write(request.user, test_case),
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
def flow_node_traceability_go(request, node_id):
    """Redirect to the traceability page of a node in the preferred view.

    Single entry point for "go to traceability": instead of every caller having
    to know whether the user prefers the graph or the matrix, they all point
    here and this view dispatches to the right page. The preference lives in the
    session (written by ``set_traceability_view``) so the whole app stays in
    sync with a single source of truth.

    Args:
        request: The incoming HTTP request.
        node_id: Primary key of the ``FlowNode`` to open the traceability for.

    Returns:
        A redirect to either the graph or the matrix traceability view for the
        given flow node, according to the session preference.
    """
    # Read the preferred mode from the session, falling back to the default.
    mode = request.session.get(TRACEABILITY_SESSION_KEY, DEFAULT_TRACEABILITY_MODE)
    # Map the mode to its URL name, guarding against stale/invalid session values.
    url_name = TRACEABILITY_URL_NAMES.get(
        mode, TRACEABILITY_URL_NAMES[DEFAULT_TRACEABILITY_MODE]
    )
    return redirect(url_name, node_id=node_id)


@login_required
def map_list(request):
    """List every ApplicationMap and allow the creation of a new one.

    Each map is prefetched with its ``referencing_nodes`` so the template can
    tell whether it is used as a sub-flow (and therefore show the
    "Info subflow use" button). Maps are also joined with their collection so
    the collection title can be displayed without N+1 queries.

    Only the maps readable by the user are listed (superusers see all). The
    create form offers the writable collections only; non-superusers must pick
    one, since maps without a collection are reserved to superusers.
    """
    maps = filter_maps(
        request.user,
        ApplicationMap.objects
        .select_related('collection')
        .order_by('-created_at')
        .prefetch_related('referencing_nodes'),
    )

    # add the coverage info to each map
    for app_map in maps:
        app_map.coverage_info = check_acceptance_criteria_coverage(app_map.uid)


    writable_collections = filter_collections(
        request.user, ApplicationMapsCollection.objects.order_by('title'), write=True,
    )
    unrestricted = is_unrestricted(request.user)
    # Search, sorting and paging are handled client-side by DataTables.
    return render(request, 'testcanvas/maps/maps_list.html', {
        'maps': maps,
        'writable_collections': writable_collections,
        # Superusers may create ungrouped maps; others need a writable collection.
        'can_create_ungrouped': unrestricted,
        'can_create_map': unrestricted or writable_collections.exists(),
    })

@login_required
def map_subflow_usage(request, pk):
    """Return the sub-flow usage list for a map as an HTMX partial.

    Lists each ``FlowNode`` that references this map through ``sub_flow``,
    together with a link to open the containing flow's editor. The response is a
    fragment (``_map_subflow_usage.html``) meant to be swapped into the
    map list sidebar by HTMX. Referencing maps the user cannot read are hidden.

    Args:
        request: The HTTP request (typically an hx-get).
        pk: Primary key of the ApplicationMap used as a sub-flow.

    Returns:
        The rendered sidebar partial.
    """
    application_map = get_object_or_404(ApplicationMap, pk=pk)
    ensure_can_read(request.user, application_map)

    # Nodes (in other maps) that reference this map as their sub-flow, limited
    # to the containing maps the user is allowed to read.
    readable_map_ids = filter_maps(request.user, ApplicationMap.objects.all()).values('pk')
    referencing_nodes = (
        application_map.referencing_nodes
        .filter(application_map_id__in=readable_map_ids)
        .select_related('application_map')
        .order_by('application_map__name', 'local_graph_id')
    )

    return render(request, 'testcanvas/maps/_maps_subflow_usage.html', {
        'application_map': application_map,
        'referencing_nodes': referencing_nodes,
    })

@require_POST
@login_required
def map_create(request):
    """Create a new (empty) ApplicationMap and jump straight into the editor.

    The optional ``collection`` POST field places the new map in a collection.
    Non-superusers must choose a collection they can write; superusers may
    leave it empty to create an ungrouped map.
    """
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, _("The flow name cannot be empty."))
        return redirect('testcanvas:map_list')

    collection_id = (request.POST.get('collection') or '').strip() or None
    collection = None
    if collection_id is not None:
        collection = ApplicationMapsCollection.objects.filter(pk=collection_id).first()

    # The service enforces the collection permission: None means "default
    # collection", writable by superusers only.
    try:
        application_map = create_application_map(request.user, name=name, collection=collection)
    except AccessDenied:
        messages.error(request, _("Select a collection you have write access to."))
        return redirect('testcanvas:map_list')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
        return redirect('testcanvas:map_list')
    messages.success(request, _("Flow '%(name)s' created.") % {"name": name})
    return redirect('testcanvas:map_editor', pk=application_map.pk)

@login_required
def dynamic_show_by_uid(request, uid):
    """Resolve any artefact UID and open its flow editor with the node highlighted.

    Given the UID of any artefact in the ISTQB chain (ApplicationMap, FlowNode,
    UserStory, AcceptanceCriterion, TestCase), this view finds the owning
    ``ApplicationMap`` and redirects to its editor. For every artefact that lives
    *inside* a flow node (FlowNode and its descendants) the containing
    ``FlowNode`` is resolved and its ``local_graph_id`` is passed as the
    ``highlight`` query parameter, so the editor can transiently highlight the
    matching Cytoscape node. The highlight is purely presentational and is never
    persisted into ``graph_data``.

    Args:
        request: The incoming HTTP request.
        uid: Any artefact UID (e.g. ``"ACU-4k9Fm2Xz8Qw1B"``).

    Returns:
        A redirect to the flow editor, optionally carrying ``?highlight=<id>``.

    Raises:
        Http404: If no artefact matches ``uid`` or it is not readable.
    """
    # A UID must never bypass the collection permissions: unreadable objects
    # answer exactly like unknown UIDs (404).
    model_obj = get_object_by_uid_or_404(request.user, uid)

    # An ApplicationMap UID opens its editor directly: there is no single node
    # to highlight, so no ``highlight`` parameter is added.
    if isinstance(model_obj, ApplicationMap):
        return redirect('testcanvas:map_editor', pk=model_obj.pk)

    # Every other artefact ultimately belongs to a FlowNode. Climb the ISTQB
    # chain (TestCase -> AC -> UserStory -> FlowNode) to the containing node so
    # the editor can highlight it via its Cytoscape id.
    if isinstance(model_obj, FlowNode):
        flow_node = model_obj
        page_url = reverse('testcanvas:map_editor', args=[flow_node.application_map_id])
        return redirect(f"{page_url}?highlight={flow_node.local_graph_id}")
    elif isinstance(model_obj, UserStory):
        user_story = model_obj
        # retrieve the flownode
        flow_node_pk = user_story.flow_node.pk
        page_url = reverse('testcanvas:flow_node_traceability', args=[flow_node_pk])
        return redirect(f"{page_url}?highlight=US_{user_story.pk}")
    elif isinstance(model_obj, AcceptanceCriterion):
        acceptance_criterion = model_obj
        # retrieve the flownode
        flow_node_pk = acceptance_criterion.user_story.flow_node.pk
        page_url = reverse('testcanvas:flow_node_traceability', args=[flow_node_pk])
        return redirect(f"{page_url}?highlight=AC_{acceptance_criterion.pk}")
    elif isinstance(model_obj, TestCase):
        test_case = model_obj
        # retrieve the flownode
        flow_node_pk = test_case.acceptance_criterion.user_story.flow_node.pk
        page_url = reverse('testcanvas:flow_node_traceability', args=[flow_node_pk])
        return redirect(f"{page_url}?highlight=TC_{test_case.pk}")
    else:
        raise Http404(f"No page suitable for show the uid: {uid}")


@login_required
def search_by_uid(request):
    """Bounce a GET search form submission to ``dynamic_show_by_uid``.

    HTML forms send the UID as a query string (``?uid=...``) and cannot fill
    the ``<str:uid>`` path segment directly, so this view only translates the
    query parameter into the resolver URL. Every lookup check (including the
    404 for unknown UIDs) is intentionally left to ``dynamic_show_by_uid``.

    Args:
        request: The incoming HTTP request carrying the ``uid`` GET parameter.

    Returns:
        A redirect to ``dynamic_show_by_uid`` for the given UID, or back to the
        flow list when the UID is empty.
    """
    uid = request.GET.get('uid', '').strip()
    # An empty UID cannot be reversed into the ``<str:uid>`` path segment
    # (it would raise NoReverseMatch), so simply go back to the flow list.
    if not uid:
        return redirect('testcanvas:map_list')
    return redirect('testcanvas:dynamic_show_by_uid', uid=uid)


@require_POST
@login_required
def clone_by_uid(request):
    """Clone the artefact identified by the POSTed ``uid`` and show the copy.

    Duplicates any artefact of the ISTQB chain (ApplicationMap, FlowNode,
    UserStory, AcceptanceCriterion, TestCase) together with everything below
    it, then redirects to ``dynamic_show_by_uid`` with the UID of the new copy,
    so the page reloads with the clone highlighted.

    Args:
        request: The incoming HTTP POST request carrying the ``uid`` field.

    Returns:
        A redirect to ``dynamic_show_by_uid`` for the cloned object, or back
        to the flow list when the UID is missing or the cloning fails.
    """
    # Local import: keeps the module-level imports untouched.
    from testcanvas.services import duplicate_by_uid

    uid = (request.POST.get('uid') or '').strip()
    if not uid:
        messages.error(request, _("No UID provided for cloning."))
        return redirect('testcanvas:map_list')

    # Cloning writes into the same flow/collection as the original, so the
    # user needs write access on it (404 if unreadable, 403 if read-only).
    get_object_by_uid_or_404(request.user, uid, write=True)

    try:
        clone = duplicate_by_uid(uid, user=request.user)
    except ValueError as exc:
        messages.error(request, _("Cloning failed: %(error)s") % {"error": exc})
        return redirect('testcanvas:map_list')

    # Human-facing label: maps have a name, nodes/stories a title, AC/TC a code.
    new_uid = clone.uid
    label = getattr(clone, 'name', None) or getattr(clone, 'title', None) or clone.code

    messages.success(
        request,
        _("Cloning completed: '%(label)s' (%(uid)s).") % {"label": label, "uid": new_uid},
    )
    # Reload the proper page with the new object highlighted.
    return redirect('testcanvas:dynamic_show_by_uid', uid=new_uid)




@login_required
def map_editor(request, pk):
    """Render the Cytoscape.js editor for a given ApplicationMap.

    Users with read-only access get the same page in read-only mode: every
    editing control is hidden and ``map_save`` rejects any write anyway.
    """
    application_map = get_object_or_404(ApplicationMap, pk=pk)
    ensure_can_read(request.user, application_map)
    user_can_write = can_write(request.user, application_map)

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
    # offer other maps the user can read; the single-level nesting / cycle
    # rules are enforced by FlowNode.clean() on save.
    subflows = [
        {'id': m.pk, 'name': m.name}
        for m in filter_maps(
            request.user,
            ApplicationMap.objects.exclude(pk=application_map.pk).order_by('name'),
        )
    ]

    # Compact, globally unique node identifiers keyed by their Cytoscape id
    # (local_graph_id). The graph itself only stores local_graph_id, so we hand
    # the front-end this mapping to display each node's stable uid.
    node_uids = {
        fn.local_graph_id: fn.uid
        for fn in application_map.relational_nodes.all()
    }

    # Collections the map can be attached to. Passed as real objects so the
    # header <select> is rendered server-side (the current one pre-selected),
    # letting the user (re)group this map on the next Save. Only writable
    # collections are offered, plus the current one so it is always displayed.
    collections = filter_collections(
        request.user, ApplicationMapsCollection.objects.all(), write=True,
    )
    if application_map.collection_id:
        collections = collections | ApplicationMapsCollection.objects.filter(
            pk=application_map.collection_id,
        )
    collections = collections.distinct().order_by('title')

    # Transient highlight marker: the Cytoscape id (local_graph_id) of a node to
    # visually emphasise when the editor is opened via a UID deep-link (see
    # ``dynamic_show_by_uid``). It is purely presentational and never persisted
    # into ``graph_data``; an empty string means "no node to highlight".
    highlight_node_id = request.GET.get('highlight', '')

    context = {
        'application_map': application_map,
        'graph_data_json': json.dumps(graph_data),
        'subflows_json': json.dumps(subflows),
        'node_uids_json': json.dumps(node_uids),
        'collections': collections,
        # Read-only mode: hides Save/Clone/Delete and the editing tools.
        'can_write': user_can_write,
        # Only superusers may detach a map from any collection.
        'can_detach_collection': is_unrestricted(request.user),
        # Node to transiently highlight (empty when the editor is opened normally).
        'highlight_node_id': highlight_node_id,
        # Plugin extension slot for the whole map (e.g. aggregate coverage).
        # Empty when no plugin is installed, so the header slot renders nothing.
        'plugin_widgets': collect_object_widgets('application_map', application_map, request),
    }
    return render(request, 'testcanvas/maps/maps_editor.html', context)

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
    ensure_can_write(request.user, application_map)

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

    # Allow renaming from the editor as well (a blank name keeps the current one).
    update_kwargs = {
        'graph_data': graph_data,
        'name': (payload.get('name') or '').strip() or None,
    }

    # Persist the rich-text description (Quill HTML) when provided.
    if 'description' in payload:
        update_kwargs['description'] = payload.get('description') or ''

    # (Re)group the map under a collection chosen in the editor header. An empty
    # value detaches the map (SET_NULL); an unknown/invalid id fails silently to
    # None ("— No collection —") so a stale option can never break the save.
    # The service checks write access on the target collection when it changes
    # (the "no collection" target is reserved to superusers).
    if 'collection' in payload:
        collection_id = payload.get('collection') or None
        update_kwargs['collection'] = (
            ApplicationMapsCollection.objects.filter(pk=collection_id).first()
            if collection_id is not None else None
        )

    # Coverage colors (presentational) are computed on the current relational
    # rows and baked into the graph BEFORE saving, so a single save persists
    # both the structure and the colors.
    _apply_coverage_colors(application_map, norm_nodes)

    # The service saves the graph, mirrors FlowNode rows (incl. node types and
    # sub-flow references) and enforces every permission / business rule in a
    # single transaction: a validation error (e.g. a cycle or illegal nesting)
    # rolls back the whole save.
    try:
        update_application_map(request.user, application_map, **update_kwargs)
    except AccessDenied as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=403)
    except ValidationError as exc:
        return JsonResponse({'ok': False, 'error': '; '.join(exc.messages)}, status=400)

    # Return the fresh local_graph_id -> uid mapping so the editor can
    # learn the UIDs of nodes created since the page was loaded (needed by the
    # "Node UUID" field and the "Clone node" operation) without a reload.
    node_uids = {
        fn.local_graph_id: fn.uid
        for fn in application_map.relational_nodes.all()
    }

    return JsonResponse({
        'ok': True,
        'graph_data': application_map.graph_data,
        'name': application_map.name,
        'node_uids': node_uids,
    })

def get_node_coverage_color(flow_node):
    """Calculate the coverage color for a FlowNode.

    Returns green (#10b981) if all UserStories have complete AcceptanceCriteria
    coverage (each AC has at least one TestCase), or yellow (#fbbf24) if any
    AC lacks a TestCase or if any UserStory lacks an AC.

    Args:
        flow_node: The ``FlowNode`` whose coverage should be evaluated, or
            ``None`` for a graph node not yet mirrored (it owns no story).

    Returns:
        A color code (hex string) representing the coverage status.
    """
    # Iterate through all user stories linked to this node.
    yellow_color = "#fbbf24"
    blue_color = "#93c5fd"
    green_color = "#86efac"
    if flow_node is None:
        return green_color
    for user_story in flow_node.user_stories.all():
        criteria = list(user_story.criteria.all())
        # US must have at least one AC; if it has none, it's incomplete.
        if not criteria:
            return yellow_color
        # All AC must have at least one TC; if any lacks a TC, it's incomplete.
        for criterion in criteria:
            if not criterion.test_cases.exists():
                return yellow_color
        # all TC complete
        return blue_color
    # All US have AC, and all AC have TC: complete coverage.
    return green_color


def _apply_coverage_colors(application_map, norm_nodes):
    """Write coverage colors into the graph nodes based on their test basis.

    Called before the map is saved: colors are computed from the current
    relational rows and written into ``norm_nodes`` in place, so the following
    save persists them together with the graph. Nodes that have no FlowNode
    row yet (just added in the editor) own no User Story, so they get the same
    color as an existing node without stories.

    Args:
        application_map: The map whose nodes should be colored.
        norm_nodes: The normalised graph nodes (``[{'data': {...}}, ...]``),
            updated in place.
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
        # Yellow if any AC lacks a TC or any US lacks an AC (see
        # get_node_coverage_color); None = node not synchronised yet.
        data['color'] = get_node_coverage_color(flow_by_id.get(str(data.get('id'))))

@login_required
def node_user_stories(request, pk, node_id):
    """HTMX endpoint: render the UserStories linked to a graph node (via FlowNode) as an HTML partial."""
    application_map = get_object_or_404(ApplicationMap, pk=pk)
    ensure_can_read(request.user, application_map)
    flow_node = application_map.relational_nodes.filter(local_graph_id=str(node_id)).first()

    # Sub-flow reference nodes delegate testing to another map, so they never own
    # User Stories: show a dedicated notice instead of the (empty) list.
    is_subflow = bool(flow_node and flow_node.node_type == FlowNode.SUBFLOW)
    user_stories = [] if is_subflow else (flow_node.user_stories.all() if flow_node else [])

    return render(request, 'testcanvas/maps/_maps_user_stories.html', {
        'flow_node': flow_node,
        'node_id': node_id,
        'user_stories': user_stories,
        'is_subflow': is_subflow,
        'can_write': can_write(request.user, application_map),
    })

@login_required
def map_delete(request, pk):
    """Delete an ApplicationMap through a dedicated confirmation page.

    To prevent accidental removal of an entire flow (with its FlowNodes,
    UserStories, AcceptanceCriteria and TestCases), deletion is a two-step
    process:

    * ``GET`` renders a confirmation page showing what will be destroyed and
      asks the user to type the exact flow name as a confirmation phrase.
    * ``POST`` performs the deletion only if the typed phrase matches the
      current flow name (case-sensitive, trimmed).

    A map used as a sub-flow by one or more ``FlowNode`` instances must not be
    deleted: doing so would leave those nodes as orphan references. In that
    case the deletion is blocked and the user is told exactly which maps/nodes
    still reference it, so the references can be removed first.

    Args:
        request: The HTTP request (GET renders the page, POST performs the
            deletion after phrase validation).
        pk: Primary key of the ApplicationMap to delete.

    Returns:
        An ``HttpResponse`` rendering the confirmation page, or a redirect
        back to the flow list on success / when deletion is blocked.
    """
    application_map = get_object_or_404(ApplicationMap, pk=pk)
    # Both the confirmation page and the deletion itself require write access.
    ensure_can_write(request.user, application_map)
    name = application_map.name

    # Nodes (in other maps) that reference this map as a sub-flow. Deleting
    # such a map would leave dangling sub-flow references, so we forbid it and
    # show the exact list of usages both on the confirm page and via a flash
    # message on POST.
    referencing_nodes = list(
        application_map.referencing_nodes
        .select_related('application_map')
        .all()
    )

    def _blocked_response():
        """Return the "cannot delete" redirect with a descriptive message."""
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

    if request.method == 'POST':
        # Sub-flow references win over the phrase check: even a matching phrase
        # must not be able to break the referential integrity of other maps.
        if referencing_nodes:
            return _blocked_response()

        typed_phrase = (request.POST.get('confirmation') or '').strip()
        if typed_phrase != name:
            # Re-render the confirmation page with an inline error so the user
            # can retry without losing context.
            return render(request, 'testcanvas/maps/maps_delete_confirm.html', {
                'application_map': application_map,
                'referencing_nodes': referencing_nodes,
                'expected_phrase': name,
                'typed_phrase': typed_phrase,
                'error': _(
                    "The confirmation phrase does not match the flow name. "
                    "Type the flow name exactly to confirm deletion."
                ),
            })

        try:
            # The service re-checks the sub-flow usage rule atomically.
            delete_artefact(request.user, application_map)
        except MapInUseAsSubflow as exc:
            # Rebinds the closure variable read by _blocked_response().
            referencing_nodes = exc.referencing_nodes
            return _blocked_response()
        messages.success(request, _("Flow '%(name)s' deleted.") % {"name": name})
        return redirect('testcanvas:map_list')

    # GET: render the confirmation page (blocked or not — we still let the user
    # see the referencing nodes so they know what to fix).
    return render(request, 'testcanvas/maps/maps_delete_confirm.html', {
        'application_map': application_map,
        'referencing_nodes': referencing_nodes,
        'expected_phrase': name,
        'typed_phrase': '',
        'error': None,
    })

# --------------------------------------------------------------------------- #
# ApplicationMapsCollection management (logical grouping layer)
# --------------------------------------------------------------------------- #

@login_required
def collection_create(request):
    """Create a new ApplicationMapsCollection.

    GET renders an empty form, POST validates it and creates the collection.
    The ``next`` target (list or tree view) is preserved so the user returns to
    the page they came from, both on save and on cancel.

    Superusers can create root collections; other users can only create
    sub-collections of a collection they can write (enforced by the form).

    An optional ``parent_collection_id`` (query string on GET, hidden input on
    POST) locks the parent field, so the "Create sub-collection" shortcut
    always creates the new collection under that parent.

    Args:
        request: The incoming HTTP request.

    Returns:
        An ``HttpResponse`` rendering the form, or a redirect to ``next`` on
        success.

    Raises:
        PermissionDenied: If a non-superuser has no writable collection at all.
    """
    if not is_unrestricted(request.user) and not get_access(request.user).writable:
        raise PermissionDenied(_("You do not have write access to any collection."))

    # Where to go back after save/cancel; falls back to the tree view.
    next_url = (
        request.POST.get('next')
        or request.GET.get('next')
        or reverse('testcanvas:collection_tree')
    )
    # Forced parent (from the "Create sub-collection" button). On GET it comes
    # from the query string; on POST it is carried by a hidden form input,
    # because the form action URL does not keep the query string.
    parent_collection_id = (
        request.POST.get('parent_collection_id')
        or request.GET.get('parent_collection_id')
        or None
    )
    form_kwargs = {'user': request.user, 'parent_collection_id': parent_collection_id}

    if request.method == 'POST':
        form = ApplicationMapsCollectionForm(request.POST, **form_kwargs)
        if form.is_valid():
            collection = form.save()
            # The new collection inherits the parent grants: refresh the cache.
            clear_access_cache(request.user)
            messages.success(request, _("Collection '%(title)s' created.") % {"title": collection.title})
            return redirect(next_url)
    else:
        form = ApplicationMapsCollectionForm(**form_kwargs)

    return render(request, 'testcanvas/collections/collections_form.html', {
        'form': form,
        'is_edit': False,
        'next_url': next_url,
        'parent_collection_id': parent_collection_id,
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
    ensure_can_write(request.user, collection)

    # Where to go back after save/cancel; falls back to the flat list view.
    next_url = (
        request.POST.get('next')
        or request.GET.get('next')
        or reverse('testcanvas:collection_tree')
    )

    if request.method == 'POST':
        form = ApplicationMapsCollectionForm(request.POST, instance=collection, user=request.user)
        if form.is_valid():
            form.save()
            # A new parent may change the inherited grants: refresh the cache.
            clear_access_cache(request.user)
            messages.success(request, _("Collection '%(title)s' updated.") % {"title": collection.title})
            return redirect(next_url)
    else:
        form = ApplicationMapsCollectionForm(instance=collection, user=request.user)

    return render(request, 'testcanvas/collections/collections_form.html', {
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

    Ungrouped maps belong to the superuser-only default collection, so a
    non-superuser is not allowed to delete a collection (or sub-tree) that
    still contains maps: they would become invisible to them.

    Args:
        request: The incoming HTTP request (POST only).
        pk: Primary key of the collection to delete.

    Returns:
        A redirect back to the collections list.
    """
    collection = get_object_or_404(ApplicationMapsCollection, pk=pk)
    ensure_can_write(request.user, collection)
    title = collection.title

    if not is_unrestricted(request.user):
        subtree_ids = [c.pk for c in collection.get_descendants(include_self=True)]
        if ApplicationMap.objects.filter(collection_id__in=subtree_ids).exists():
            messages.error(
                request,
                _(
                    "Collection '%(title)s' cannot be deleted: it (or one of its "
                    "sub-collections) still contains flows. Move or delete them first."
                ) % {"title": title},
            )
            return redirect('testcanvas:collection_tree')

    collection.delete()
    messages.success(request, _("Collection '%(title)s' deleted.") % {"title": title})
    return redirect('testcanvas:collection_tree')

@login_required
def project_field_settings(request):
    """Show and update which optional fields are visible globally.

    Simple settings page that lists every optional field declared in the
    catalogue (grouped by model) with an on/off checkbox reflecting the current
    global preferences. Saving performs a bulk ``update_or_create`` so fields
    can be personalised in one place.

    Args:
        request: The incoming HTTP request (GET renders, POST saves).

    Returns:
        An ``HttpResponse`` rendering the settings page, or a redirect back to it
        after a successful save.

    Raises:
        PermissionDenied: If the user is not a superuser. The preferences are
            global (they affect every user and collection), so only superusers
            may view or change them.
    """
    if not is_unrestricted(request.user):
        raise PermissionDenied(_("Only superusers can manage the optional fields settings."))

    from testcanvas.models import FieldVisibilityPreference
    from testcanvas.utilities.optional_fields import OPTIONAL_FIELDS

    if request.method == 'POST':
        # Checkboxes submit "<model>:<field>" for every enabled field.
        enabled = set(request.POST.getlist('visible_fields'))
        for model_name, specs in OPTIONAL_FIELDS.items():
            for spec in specs:
                key = f"{model_name}:{spec.name}"
                FieldVisibilityPreference.objects.update_or_create(
                    target_model=model_name,
                    field_name=spec.name,
                    defaults={'is_visible': key in enabled},
                )
        messages.success(request, _("Field visibility preferences saved."))
        return redirect('testcanvas:project_field_settings')

    # Build the display structure: one section per model, each field carrying
    # its current visibility state (default off when no preference row exists).
    current = {
        (pref.target_model, pref.field_name): pref.is_visible
        for pref in FieldVisibilityPreference.objects.all()
    }
    sections = []
    for model_name, specs in OPTIONAL_FIELDS.items():
        fields = [
            {
                'key': f"{model_name}:{spec.name}",
                'label': spec.label,
                'is_visible': current.get((model_name, spec.name), False),
            }
            for spec in specs
        ]
        sections.append({'model_name': model_name, 'fields': fields})

    return render(request, 'testcanvas/settings/settings_project_fields.html', {
        'sections': sections,
    })




