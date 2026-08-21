"""Coverage computation for TestCanvas nodes and traceability artifacts.

Provides functions to determine coverage status based on the UserStory → AcceptanceCriterion
→ TestCase chain.
"""


def is_node_complete(flow_node) -> bool:
    """Check if a FlowNode's test basis is complete.

    A node is complete if:
    - It has no UserStories (edge case: no testing needed), OR
    - All its UserStories have at least one AcceptanceCriterion, AND
    - All those AcceptanceCriteria have at least one TestCase attached.

    Args:
        flow_node: The FlowNode instance to check.

    Returns:
        True if the node is complete (or has no stories), False otherwise.
    """
    user_stories = list(flow_node.user_stories.prefetch_related('criteria__test_cases').all())

    # Edge case: no stories means no testing needed (trivially complete).
    if not user_stories:
        return True

    # Every story must have at least one criterion, and every criterion must have
    # at least one test case.
    for story in user_stories:
        criteria = list(story.criteria.all())
        
        # Story with no criteria → incomplete.
        if not criteria:
            return False
        
        # Any criterion with no test cases → incomplete.
        for criterion in criteria:
            if not criterion.test_cases.exists():
                return False

    return True


def get_node_coverage_color(flow_node) -> str:
    """Return the display color for a FlowNode based on its coverage status.

    Args:
        flow_node: The FlowNode instance to evaluate.

    Returns:
        '#10b981' (green) if complete, '#fbbf24' (yellow) if incomplete.
    """
    return '#10b981' if is_node_complete(flow_node) else '#fbbf24'

