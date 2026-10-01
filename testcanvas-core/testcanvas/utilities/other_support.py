"""Resolve any TestCanvas UID back to its owning ApplicationMap."""

from typing import Optional

from testcanvas.models import (
    AcceptanceCriterion,
    ApplicationMap,
    FlowNode,
    TestCase,
    UserStory,
)


def find_model_object_by_uid(uid: str) -> None | ApplicationMap | FlowNode | UserStory | AcceptanceCriterion | TestCase:
    """ identifica e ritorna l'oggetto del modello che ha l'UID passato."""


    if not isinstance(uid, str):
        raise ValueError("uid must be a string.")

    uid = uid.strip()
    if not uid:
        raise ValueError("uid must be a non-empty string.")

    # Is it an ApplicationMap UID? Then it is already the map we want.
    application_map = ApplicationMap.objects.filter(flow_uid=uid).first()
    if application_map is not None:
        return application_map

    # Is it a FlowNode UID? Climb one step up to its map.
    flow_node = FlowNode.objects.filter(node_uid=uid).first()
    if flow_node is not None:
        return flow_node

    # Is it a UserStory UID? Climb: UserStory -> FlowNode -> ApplicationMap.
    user_story = UserStory.objects.filter(user_story_uid=uid).first()
    if user_story is not None:
        return user_story

    # Is it an AcceptanceCriterion UID?
    # Climb: AcceptanceCriterion -> UserStory -> FlowNode -> ApplicationMap.
    criterion = AcceptanceCriterion.objects.filter(ac_uid=uid).first()
    if criterion is not None:
        return criterion

    # Is it a TestCase UID? Climb the full chain:
    # TestCase -> AcceptanceCriterion -> UserStory -> FlowNode -> ApplicationMap.
    test_case = TestCase.objects.filter(tc_uid=uid).first()
    if test_case is not None:
        return test_case

    # No artefact matched the UID.
    return None