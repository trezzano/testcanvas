import networkx as nx
from django.db import models

# Schema concettuale fondamentale :
# UserStory  1 ──< N  AcceptanceCriterion  N ──< >── N  TestCase

class ApplicationMap(models.Model):
    """
    Main container for the application flow graph. 
    Uses NetworkX for graph logic and serializes natively into Cytoscape.js format.
    """
    name = models.CharField(max_length=150, help_text="Global flow name (e.g., 'Checkout Flow')")
    created_at = models.DateTimeField(auto_now_add=True)

    # JSON field where NetworkX saves the entire structure (nodes, edges, and visual styles)
    graph_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structure natively exported by NetworkX in Cytoscape format"
    )

    class Meta:
        verbose_name = "Application Map"
        verbose_name_plural = "Application Maps"

    def __str__(self):
        return self.name

    def get_graph(self) -> nx.DiGraph:
        """Reconstructs and returns the NetworkX Directed Graph object."""
        if not self.graph_data:
            return nx.DiGraph()
        # Converts the Cytoscape JSON format back into a NetworkX directed graph
        return nx.cytoscape_graph(self.graph_data)

    def save_graph(self, G: nx.DiGraph):
        """Takes a NetworkX graph, converts it to Cytoscape format, and saves it to the database."""
        self.graph_data = nx.cytoscape_data(G)
        self.save()

    def save(self, *args, **kwargs):
        """Persist the map, then keep the relational FlowNode rows mirroring graph_data."""
        super().save(*args, **kwargs)
        self.sync_flow_nodes()

    def _extract_graph_nodes(self) -> dict:
        """Return a mapping {node_id: {'title', 'description'}} from graph_data."""
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
    """The bridge between the visual graph (NetworkX/Cytoscape) and the ISTQB relational test data."""
    application_map = models.ForeignKey(ApplicationMap, on_delete=models.CASCADE, related_name='relational_nodes')
    local_graph_id = models.CharField(max_length=50, help_text="ID matching the node.data.id inside the NetworkX graph")
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ('application_map', 'local_graph_id')
        verbose_name = "Flow Node"
        verbose_name_plural = "Flow Nodes"

    def __str__(self):
        return f"{self.local_graph_id} - {self.title}"

class UserStory(models.Model):
    """ISTQB / Agile: Stories associated with a specific step or state of the application flow."""
    flow_node = models.ForeignKey(FlowNode, on_delete=models.CASCADE, related_name='user_stories')
    code = models.CharField(max_length=20, help_text="E.g., US-01")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "User Stories"

    def __str__(self):
        return f"{self.code} - {self.title}"

class AcceptanceCriterion(models.Model):
    """Detailed requirements and acceptance criteria bound to the User Story."""
    user_story = models.ForeignKey(UserStory, on_delete=models.CASCADE, related_name='criteria')
    code = models.CharField(max_length=20, help_text="E.g., AC-01.1")
    text = models.TextField()

    class Meta:
        verbose_name = "Acceptance Criterion"
        verbose_name_plural = "Acceptance Criteria"

    def __str__(self):
        return f"{self.code}"

class TestCase(models.Model):
    """ISTQB: Actual and executable test cases linked to individual criteria."""
    criteria = models.ManyToManyField(
        AcceptanceCriterion,
        related_name='test_cases',
        help_text="One or more acceptance criteria validated by this test case",
    )
    test_code = models.CharField(max_length=20, help_text="E.g., TC-001")
    title = models.CharField(max_length=150)
    preconditions = models.TextField(blank=True)
    steps = models.TextField(help_text="Sequence of textual actions separated by newlines")
    expected_result = models.TextField()
    # i risultati attuali del test sono delegati 
    # ai sistemi di test automatici o manuali esterni, quindi non li memorizziamo qui.
    

    STATUS_CHOICES = [
        ('TO_EXECUTE', 'To Execute'),
        ('PASSED', 'Passed'),
        ('FAILED', 'Failed'),
        ('BLOCKED', 'Blocked'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='TO_EXECUTE')

    class Meta:
        verbose_name = "Test Case"
        verbose_name_plural = "Test Cases"

    def __str__(self):
        return f"{self.test_code} - {self.title}"