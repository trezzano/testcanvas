import uuid

from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

# Schema concettuale fondamentale :
# UserStory  1 ──< N  AcceptanceCriterion  N ──< >── N  TestCase

# Base62 alphabet used to render a 128-bit UUID as a short, URL-safe token.
_BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _int_to_base62(value: int) -> str:
    """Encode a non-negative integer into a Base62 string.

    Args:
        value: The non-negative integer to encode.

    Returns:
        The Base62 representation of ``value`` (``"0"`` when ``value`` is 0).
    """
    if value == 0:
        return _BASE62_ALPHABET[0]
    base = len(_BASE62_ALPHABET)
    digits = []
    while value:
        value, remainder = divmod(value, base)
        digits.append(_BASE62_ALPHABET[remainder])
    return "".join(reversed(digits))


def generate_compact_node_uid() -> str:
    """Return a compact, globally unique node identifier.

    Encodes a random UUID4 (128 bits) into a Base62 string, producing a short
    (up to 22 characters) collision-resistant, URL-safe token. It is stable
    across environments and re-imports, so it is safe to hand to an external
    agent (LLM) as a persistent node reference.

    Returns:
        A Base62-encoded UUID4 string, without padding.
    """
    return _int_to_base62(uuid.uuid4().int)


class ApplicationMapsCollection(models.Model):
    """Logical grouping layer that gathers several ``ApplicationMap`` records.

    A collection is a purely organisational container: it does not own any
    graph data itself, it only groups related application flows so they can be
    reasoned about together (e.g. all the flows of a given product area).

    Attributes:
        title: Human-readable name of the collection.
        description: Rich-text (HTML) description stored as produced by the
            front-end editor (Quill), mirroring ``ApplicationMap.description``.
        background_color: Hex color used as the collection's background accent.
        created_at: Creation timestamp, set automatically.
    """

    # Validator ensuring the color is a 3- or 6-digit hex value (e.g. #fff, #ffffff).
    _HEX_COLOR_VALIDATOR = RegexValidator(
        regex=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$",
        message=_("Enter a valid hex color, e.g. #ffffff."),
    )

    title = models.CharField(
        max_length=150,
        help_text=_("Collection title (e.g., 'Checkout Area')."),
    )
    # Rich-text HTML description, edited in the front-end and stored verbatim,
    # exactly like ApplicationMap.description.
    description = models.TextField(
        blank=True,
        help_text=_("Rich-text (HTML) description of the collection."),
    )
    background_color = models.CharField(
        max_length=7,
        default="#ffffff",
        validators=[_HEX_COLOR_VALIDATOR],
        help_text=_("Background color as a hex value (e.g., #ffffff)."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Application Maps Collection")
        verbose_name_plural = _("Application Maps Collections")
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title


class ApplicationMap(models.Model):
    """
    Main container for the application flow graph. 
    Uses serializes natively into Cytoscape.js format.
    """
    name = models.CharField(max_length=150, help_text=_("Global flow name (e.g., 'Checkout Flow')"))
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True)

    flow_uid = models.CharField(
        max_length=22,
        unique=True,
        default=generate_compact_node_uid,
        editable=False,
        db_index=True,
        help_text=_("Compact, globally unique flow identifier (Base62 UUID4) usable as a stable LLM reference."),
    )

    # Optional logical grouping. SET_NULL keeps the map if its collection is
    # deleted (the map simply becomes ungrouped).
    collection = models.ForeignKey(
        ApplicationMapsCollection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maps",
        help_text=_("Optional collection this map belongs to."),
    )

    # JSON field where NetworkX saves the entire structure (nodes, edges, and visual styles)
    # in cytoscape format
    graph_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Structure in Cytoscape format")
    )

    class Meta:
        verbose_name = _("Application Map")
        verbose_name_plural = _("TestCanvas App")

    def __str__(self):
        return self.name


    def save(self, *args, **kwargs):
        """Persist the map, then keep the relational FlowNode rows mirroring graph_data."""
        super().save(*args, **kwargs)
        self.sync_flow_nodes()

    def _extract_graph_nodes(self) -> dict:
        """Return a mapping {node_id: {'title', 'description'}} from graph_data.

        Only ``title`` and ``description`` are mirrored here. ``node_type`` and
        ``sub_flow`` are intentionally NOT touched by the sync so they survive a
        re-save of the graph.
        """
        nodes = {}
        elements = (self.graph_data or {}).get('elements', {})
        for node in elements.get('nodes', []):
            data = node.get('data', {})
            node_id = data.get('id')
            if node_id is None:
                continue
            nodes[str(node_id)] = {
                'title': (data.get('name') or '')[:100],
                'description': data.get('description') or '',
            }
        return nodes

    def sync_flow_nodes(self):
        """
        Mirror the nodes stored in graph_data into the FlowNode table.

        - nodes present in graph_data but missing in FlowNode  -> created
        - nodes present in FlowNode but missing in graph_data  -> deleted
        - nodes present in both                                -> updated if changed
        """
        graph_nodes = self._extract_graph_nodes()
        existing = {fn.local_graph_id: fn for fn in self.relational_nodes.all()}

        # Remove FlowNodes that no longer exist in graph_data
        stale_ids = [node_id for node_id in existing if node_id not in graph_nodes]
        if stale_ids:
            self.relational_nodes.filter(local_graph_id__in=stale_ids).delete()

        # Create or update FlowNodes to match graph_data
        for node_id, info in graph_nodes.items():
            flow_node = existing.get(node_id)
            if flow_node is None:
                FlowNode.objects.create(
                    application_map=self,
                    local_graph_id=node_id,
                    title=info['title'],
                    description=info['description'],
                )
            elif flow_node.title != info['title'] or flow_node.description != info['description']:
                flow_node.title = info['title']
                flow_node.description = info['description']
                flow_node.save(update_fields=['title', 'description'])

class FlowNode(models.Model):
    """The bridge between the visual graph (NetworkX/Cytoscape) and the ISTQB relational test data.

    A FlowNode is either a *pure node* that owns its own UserStory tree, or a
    *sub-flow reference* that delegates testing to another ApplicationMap.
    """

    # Node nature: discriminates a testable leaf from a sub-flow reference.
    PURE = "PURE"
    SUBFLOW = "SUBFLOW"
    NODE_TYPE_CHOICES = [
        (PURE, _("Pure Node")),
        (SUBFLOW, _("Sub-flow Reference")),
    ]

    application_map = models.ForeignKey(ApplicationMap, on_delete=models.CASCADE, related_name='relational_nodes')
    local_graph_id = models.CharField(max_length=50, help_text=_("ID matching the node.data.id inside the NetworkX graph"))
    # Compact, globally unique identifier (Base62-encoded UUID4). Unlike
    # local_graph_id (unique only within a single map), this value is unique
    # across every map, so it is safe to expose as a stable node reference,
    # e.g. to an LLM.
    node_uid = models.CharField(
        max_length=22,
        unique=True,
        default=generate_compact_node_uid,
        editable=False,
        db_index=True,
        help_text=_("Compact, globally unique node identifier (Base62 UUID4) usable as a stable LLM reference."),
    )
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    # Nature of the node (pure testable leaf vs. reference to another flow).
    node_type = models.CharField(
        max_length=10,
        choices=NODE_TYPE_CHOICES,
        default=PURE,
        help_text=_(
            "PURE: node owns its UserStory tree. "
            "SUBFLOW: node references another ApplicationMap as a sub-flow."
        ),
    )

    # Target map when this node is a sub-flow reference. SET_NULL keeps the node
    # if the referenced map is deleted (it becomes an orphan to be fixed).
    sub_flow = models.ForeignKey(
        ApplicationMap,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referencing_nodes",
        help_text=_("Target ApplicationMap when node_type is SUBFLOW."),
    )

    class Meta:
        unique_together = ('application_map', 'local_graph_id')
        verbose_name = _("Flow Node")
        verbose_name_plural = _("Flow Nodes")

    def __str__(self):
        return f"{self.local_graph_id} - {self.title}"

    def clean(self) -> None:
        """Validate the pure/reference invariants before persisting.

        Enforces the single-level nesting and single-output philosophy:

        * ``node_type`` and ``sub_flow`` must be coherent;
        * a node cannot reference its own map;
        * a referenced map cannot itself contain SUBFLOW nodes (depth == 1);
        * a reference must not create a cycle;
        * a SUBFLOW node must not own UserStory leaves.

        Raises:
            ValidationError: If any invariant is violated.
        """
        from django.core.exceptions import ValidationError

        # 1. node_type <-> sub_flow coherence.
        if self.node_type == self.SUBFLOW and self.sub_flow_id is None:
            raise ValidationError(
                {"sub_flow": _("A SUBFLOW node must reference a sub-flow map.")}
            )
        if self.node_type == self.PURE and self.sub_flow_id is not None:
            raise ValidationError(
                {"sub_flow": _("A PURE node must not reference a sub-flow map.")}
            )

        if self.sub_flow_id is not None:
            # 2. No self-reference.
            if self.sub_flow_id == self.application_map_id:
                raise ValidationError(
                    {"sub_flow": _("A node cannot reference its own map.")}
                )

            # 3. Single-level nesting: the referenced map must be "flat"
            #    (it must not contain any SUBFLOW node).
            if self.sub_flow.relational_nodes.filter(node_type=self.SUBFLOW).exists():
                raise ValidationError(
                    {"sub_flow": _(
                        "The referenced map already contains sub-flow nodes; "
                        "only single-level nesting is allowed."
                    )}
                )

            # 4. Cycle prevention: the referenced map must not (directly or
            #    indirectly) reference this node's own map.
            if self._creates_cycle(self.sub_flow, target_map_id=self.application_map_id):
                raise ValidationError(
                    {"sub_flow": _("This reference would create a cycle between maps.")}
                )

        # 5. A reference node must not own its own leaves.
        if self.node_type == self.SUBFLOW and self.pk and self.user_stories.exists():
            raise ValidationError(
                _("A SUBFLOW node cannot own User Stories; leaves live in the sub-flow.")
            )

    def _creates_cycle(self, start_map: "ApplicationMap", target_map_id: int) -> bool:
        """Return True if following sub_flow references reaches ``target_map_id``.

        Walks the sub-flow references starting from ``start_map`` and reports
        whether ``target_map_id`` (this node's own map) is reachable, which would
        close a loop.

        Args:
            start_map: The map we are about to reference.
            target_map_id: The id of this node's own map.

        Returns:
            True if a cycle would be created, False otherwise.
        """
        visited: set[int] = set()
        stack = [start_map.pk]
        while stack:
            current = stack.pop()
            if current == target_map_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            # Maps referenced by the sub-flow nodes contained in `current`.
            stack.extend(
                FlowNode.objects.filter(application_map_id=current)
                .exclude(sub_flow_id__isnull=True)
                .values_list("sub_flow_id", flat=True)
            )
        return False


class UserStory(models.Model):
    """ISTQB / Agile: Stories associated with a specific step or state of the application flow."""

    # Standard priority levels for ISTQB Risk-Based Testing
    class Priority(models.TextChoices):
        HIGH = 'HIGH', _('High')
        MEDIUM = 'MEDIUM', _('Medium')
        LOW = 'LOW', _('Low')

    description = models.TextField(blank=True)

    user_story_uid = models.CharField(
        max_length=22,
        unique=True,
        default=generate_compact_node_uid,
        editable=False,
        db_index=True,
        help_text=_("Compact, globally unique node identifier (Base62 UUID4) usable as a stable LLM reference."),
    )

    flow_node = models.ForeignKey(
        'FlowNode',
        on_delete=models.CASCADE,
        related_name='user_stories',
        verbose_name=_("Flow Node")
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        help_text=_("Unique identifier ensuring ISTQB vertical traceability. E.g., US-01"),
        verbose_name=_("Code")
    )
    title = models.CharField(
        max_length=150,
        verbose_name=_("Title")
    )

    # Breakdown to enforce Agile syntax structure
    as_a = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("The actor/role persona (e.g., Guest Customer)"),
        verbose_name=_("As a...")
    )
    i_want_to = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("The core action or feature required from the system"),
        verbose_name=_("I want to...")
    )
    so_that = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("The underlying business value or user benefit"),
        verbose_name=_("So that...")
    )

    # Extra technical context or constraints
    additional_notes = models.TextField(
        blank=True,
        help_text=_("Technical constraints, business rules, or extra context"),
        verbose_name=_("Additional Notes")
    )

    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        verbose_name=_("Priority")
    )

    class Meta:
        verbose_name = _("User Story")
        verbose_name_plural = _("User Stories")
        ordering = ['code']  # Keeps stories ordered sequentially in test reports

    def __str__(self):
        return f"{self.code} - {self.title}"

    @property
    def full_statement(self):
        """Returns the standard Agile user story narrative statement."""
        if self.as_a and self.i_want_to and self.so_that:
            return _("As a %(as_a)s, I want to %(i_want_to)s so that %(so_that)s.") % {
                "as_a": self.as_a,
                "i_want_to": self.i_want_to,
                "so_that": self.so_that,
            }
        return self.title


class AcceptanceCriterion(models.Model):
    """Detailed requirements and acceptance criteria bound to the User Story."""
    user_story = models.ForeignKey(UserStory, on_delete=models.CASCADE, related_name='criteria')
    code = models.CharField(max_length=20, help_text=_("E.g., AC-01.1"))
    text = models.TextField()

    ac_uid = models.CharField(
        max_length=22,
        unique=True,
        default=generate_compact_node_uid,
        editable=False,
        db_index=True,
        help_text=_("Compact, globally unique node identifier (Base62 UUID4) usable as a stable LLM reference."),
    )

    # ISTQB: distinguishes functional criteria (what the system does) from
    # non-functional ones (how the system behaves: performance, security, etc.).
    # True  -> functional criterion.
    # False -> non-functional criterion.
    is_functional = models.BooleanField(
        default=True,
        help_text=_("True if the criterion is functional, False if non-functional."),
    )

    class Meta:
        verbose_name = _("Acceptance Criterion")
        verbose_name_plural = _("Acceptance Criteria")

    def __str__(self):
        return f"{self.code}"

class TestCase(models.Model):
    """ISTQB: Actual and executable test cases linked to individual criteria."""
    criteria = models.ManyToManyField(
        AcceptanceCriterion,
        related_name='test_cases',
        help_text=_("One or more acceptance criteria validated by this test case"),
    )
    test_code = models.CharField(max_length=20, help_text=_("E.g., TC-001"))
    title = models.CharField(max_length=150)
    preconditions = models.TextField(blank=True)
    steps = models.TextField(help_text=_("Sequence of textual actions separated by newlines"))
    expected_result = models.TextField()

    tc_uid = models.CharField(
        max_length=22,
        unique=True,
        default=generate_compact_node_uid,
        editable=False,
        db_index=True,
        help_text=_("Compact, globally unique node identifier (Base62 UUID4) usable as a stable LLM reference."),
    )

    # i risultati attuali del test sono delegati 
    # ai sistemi di test automatici o manuali esterni, quindi non li memorizziamo qui.

    STATUS_CHOICES = [
        ('TO_EXECUTE', _('To Execute')),
        ('PASSED', _('Passed')),
        ('FAILED', _('Failed')),
        ('BLOCKED', _('Blocked')),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='TO_EXECUTE')

    class Meta:
        verbose_name = _("Test Case")
        verbose_name_plural = _("Test Cases")

    def __str__(self):
        return f"{self.test_code} - {self.title}"