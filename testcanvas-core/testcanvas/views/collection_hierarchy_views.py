"""Views handling the nested (folder/sub-folder) hierarchy of collections.

These views complement the flat CRUD views living in ``standard_views`` by
adding the tree-specific operations introduced with the self-referential
``ApplicationMapsCollection.parent`` field:

* :func:`collection_tree` — render the whole nested tree of collections;
* :func:`collection_detail` — HTMX detail card shown in the sidebar;
* :func:`collection_move` — re-parent a collection (drag & drop / move action).

They are intentionally kept out of ``standard_views`` so the hierarchy concern
stays isolated and easy to evolve.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from testcanvas.models import ApplicationMap, ApplicationMapsCollection


def _serialize_tree(collection: ApplicationMapsCollection, highlight_collection_id: int | None = None) -> dict:
    """Recursively serialize a collection and its descendants into a dict tree.

    Args:
        collection: The root collection of the (sub)tree to serialize.
        highlight_collection_id: Optional collection ID to mark as highlighted.

    Returns:
        A nested dictionary describing the collection, its member maps count,
        children, and whether it should be highlighted.
    """
    return {
        "id": collection.pk,
        "title": collection.title,
        "background_color": collection.background_color,
        # Number of ApplicationMaps directly grouped by this collection.
        "maps_count": collection.maps.count(),
        "is_highlighted": collection.pk == highlight_collection_id,
        "children": [_serialize_tree(child, highlight_collection_id) for child in collection.children.all()],
    }


@login_required
def collection_tree(request, application_map_uid=None):
    """Render the complete nested tree of collections.
    Starts from the root collections (``parent`` is ``None``) and walks down the
    ``children`` relation to build a folder-like tree.
    If ``application_map_uid`` is provided, the collection containing that
    ApplicationMap is highlighted in the tree. Unknown UIDs are ignored.
    Args:
        request: The incoming HTTP request.
        application_map_uid: Optional application map UID from the URL.
    Returns:
        An ``HttpResponse`` rendering the collections tree page.
    """
    highlight_collection_id = None
    if application_map_uid:
        app_map = ApplicationMap.objects.filter(flow_uid=application_map_uid).first()
        if app_map:
            highlight_collection_id = app_map.collection_id
    roots = (
        ApplicationMapsCollection.objects
        .filter(parent__isnull=True)
        .order_by("title")
    )
    tree = [_serialize_tree(root, highlight_collection_id) for root in roots]
    return render(request, "testcanvas/collections/collections_tree.html", {"tree": tree})
@login_required
def collection_detail(request, pk):
    """Render a collection detail card as an HTMX partial.

    Loaded into the shared detail sidebar (``#detail-sidebar-body``) when a
    collection title is clicked in the tree view. Shows the linked maps plus the
    edit and delete actions, mirroring the User Story / AC / Test Case detail
    cards used by the traceability views.

    Args:
        request: The incoming HTTP request (typically an hx-get).
        pk: Primary key of the collection to display.

    Returns:
        An ``HttpResponse`` rendering the collection detail partial.
    """
    collection = get_object_or_404(
        ApplicationMapsCollection.objects.prefetch_related("maps"),
        pk=pk,
    )
    return render(request, "testcanvas/collections/_collections_detail.html", {
        "collection": collection,
        "maps": collection.maps.order_by("name"),
    })


@require_POST
@login_required
def collection_move(request, pk):
    """Move a collection under a new parent (or to the top level).

    Reads the target parent from the ``parent_id`` POST parameter. An empty or
    missing value moves the collection to the root. The move is validated by
    ``ApplicationMapsCollection.move_to`` (and thus ``clean``), so self-references
    and cycles are rejected.

    Args:
        request: The incoming HTTP request (POST only).
        pk: Primary key of the collection to move.

    Returns:
        A ``JsonResponse`` describing the outcome for HTMX/AJAX callers, or a
        redirect to the tree page for a standard form submit.
    """
    collection = get_object_or_404(ApplicationMapsCollection, pk=pk)

    raw_parent_id = request.POST.get("parent_id") or ""
    new_parent = None
    if raw_parent_id.strip():
        new_parent = get_object_or_404(ApplicationMapsCollection, pk=raw_parent_id)

    try:
        collection.move_to(new_parent)
    except ValidationError as exc:
        message = "; ".join(exc.messages)
        # Answer AJAX/HTMX callers with JSON, plain form posts with a redirect.
        if request.headers.get("HX-Request") or request.content_type == "application/json":
            return JsonResponse({"ok": False, "error": message}, status=400)
        messages.error(request, message)
        return redirect("testcanvas:collection_tree")

    success = _("Collection '%(title)s' moved.") % {"title": collection.title}
    if request.headers.get("HX-Request") or request.content_type == "application/json":
        return JsonResponse({
            "ok": True,
            "id": collection.pk,
            "parent_id": collection.parent_id,
            "full_path": collection.get_full_path(),
        })
    messages.success(request, success)
    return redirect("testcanvas:collection_tree")
