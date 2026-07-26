from django import forms

from .models import (
    AcceptanceCriterion,
    ApplicationMapsCollection,
    TestCase,
    UserStory,
)


class ApplicationMapsCollectionForm(forms.ModelForm):
    """ModelForm to create/edit an ApplicationMapsCollection.

    The ``description`` is a rich-text (HTML) field edited on the front-end
    through a Quill editor; the underlying widget is a hidden textarea that Quill
    keeps in sync. ``background_color`` uses an HTML5 color input.
    """

    class Meta:
        model = ApplicationMapsCollection
        fields = ("title", "description", "background_color")
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "e.g. Checkout Area",
            }),
            # Hidden textarea backing the Quill editor; the visible editor lives
            # in the template and writes its HTML here before submit.
            "description": forms.Textarea(attrs={
                "id": "collection-description",
                "hidden": True,
            }),
            # Native color picker; stores the value as a hex string (#rrggbb).
            "background_color": forms.TextInput(attrs={
                "type": "color",
                "class": "field-color",
            }),
        }
        labels = {
            "background_color": "Background color",
        }


class UserStoryForm(forms.ModelForm):
    """ModelForm to create/edit a UserStory bound to a FlowNode.

    Exposes the full ISTQB/Agile UserStory model: the identifier fields
    (``code``/``title``), the free-text ``description``, the Agile breakdown
    (``as_a``/``i_want_to``/``so_that``), ``additional_notes`` and the
    risk-based ``priority`` level.
    """

    class Meta:
        model = UserStory
        fields = (
            "code",
            "title",
            "priority",
            "description",
            "as_a",
            "i_want_to",
            "so_that",
            "additional_notes",
        )
        widgets = {
            "code": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "e.g. US-01",
            }),
            "title": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "Short user story title",
            }),
            "priority": forms.Select(attrs={
                "class": "field-input",
            }),
            "description": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 3,
                "placeholder": "Summary or extra context for the story",
            }),
            "as_a": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "e.g. Guest Customer",
            }),
            "i_want_to": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "The core action or feature required",
            }),
            "so_that": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "The business value or user benefit",
            }),
            "additional_notes": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 3,
                "placeholder": "Technical constraints, business rules, extra context",
            }),
        }


class AcceptanceCriterionForm(forms.ModelForm):
    """Simple ModelForm to create/edit an AcceptanceCriterion bound to a UserStory."""

    class Meta:
        model = AcceptanceCriterion
        fields = ("code", "text", "is_functional")
        widgets = {
            "code": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "e.g. AC-01.1",
            }),
            "text": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 4,
                "placeholder": "Given <context> when <action> then <outcome>",
            }),
            # Dropdown to pick whether the criterion is functional or not.
            "is_functional": forms.Select(
                choices=((True, "Functional"), (False, "Non-functional")),
                attrs={"class": "field-input"},
            ),
        }
        labels = {
            "is_functional": "Criterion type",
        }


class TestCaseForm(forms.ModelForm):
    """ModelForm to create/edit a TestCase and its linked acceptance criteria."""

    class Meta:
        model = TestCase
        fields = (
            "test_code",
            "title",
            "criteria",
            "preconditions",
            "steps",
            "expected_result",
            "status",
        )
        widgets = {
            "test_code": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "e.g. TC-001",
            }),
            "title": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "Short test case title",
            }),
            "criteria": forms.SelectMultiple(attrs={
                "class": "field-input",
                "size": 6,
            }),
            "preconditions": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 3,
                "placeholder": "State required before running the test",
            }),
            "steps": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 5,
                "placeholder": "One action per line",
            }),
            "expected_result": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 3,
                "placeholder": "Expected outcome",
            }),
            "status": forms.Select(attrs={
                "class": "field-input",
            }),
        }


