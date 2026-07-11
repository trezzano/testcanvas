from django import forms

from .models import AcceptanceCriterion, TestCase, UserStory


class UserStoryForm(forms.ModelForm):
    """Simple ModelForm to create/edit a UserStory bound to a FlowNode."""

    class Meta:
        model = UserStory
        fields = ("code", "title", "description")
        widgets = {
            "code": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "e.g. US-01",
            }),
            "title": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": "Short user story title",
            }),
            "description": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 3,
                "placeholder": "As a <role> I want <goal> so that <benefit>",
            }),
        }


class AcceptanceCriterionForm(forms.ModelForm):
    """Simple ModelForm to create/edit an AcceptanceCriterion bound to a UserStory."""

    class Meta:
        model = AcceptanceCriterion
        fields = ("code", "text")
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


