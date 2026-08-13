from django import forms
from django.utils.translation import gettext_lazy as _

from .models import (
    AcceptanceCriterion,
    ApplicationMapsCollection,
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
                "placeholder": _("e.g. Checkout Area"),
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
            "background_color": _("Background color"),
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
                "placeholder": _("e.g. US-01"),
            }),
            "title": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": _("Short user story title"),
            }),
            "priority": forms.Select(attrs={
                "class": "field-input",
            }),
            "description": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 3,
                "placeholder": _("Summary or extra context for the story"),
            }),
            "as_a": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": _("e.g. Guest Customer"),
            }),
            "i_want_to": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": _("The core action or feature required"),
            }),
            "so_that": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": _("The business value or user benefit"),
            }),
            "additional_notes": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 3,
                "placeholder": _("Technical constraints, business rules, extra context"),
            }),
        }


class AcceptanceCriterionForm(forms.ModelForm):
    """ModelForm to create/edit an AcceptanceCriterion bound to a UserStory.

    Exposes the new split between business description and optional BDD text,
    plus the full ISTQB/ISO 25010 criterion type taxonomy.

    The optional ``gherkin_text`` field is designed for content pasted from an
    external LLM/editor. The form stays permissive and only performs lightweight
    normalization so pasted content is stored consistently without blocking the
    user on syntax quality.
    """

    class Meta:
        model = AcceptanceCriterion
        fields = ("code", "description", "gherkin_text", "criterion_type")
        widgets = {
            "code": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": _("e.g. AC-01.1"),
            }),
            "description": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 4,
                "placeholder": _("Business rule, expected behaviour, or acceptance condition"),
            }),
            # Optional pure BDD scenario; shown always for explicit authoring.
            "gherkin_text": forms.Textarea(attrs={
                "class": "field-input gherkin-editor",
                "rows": 14,
                "spellcheck": "false",
                "autocomplete": "off",
                "autocapitalize": "off",
                "placeholder": _(
                    "Scenario: Successful payment\n"
                    "Given the customer is on the checkout page\n"
                    "When the customer confirms the order\n"
                    "Then the system creates the order"
                ),
            }),
            "criterion_type": forms.Select(attrs={"class": "field-input"}),
        }
        labels = {
            "description": _("Description"),
            "gherkin_text": _("Gherkin scenario (optional)"),
            "criterion_type": _("Criterion type"),
        }

    def _normalize_gherkin_text(self, value: str) -> str:
        """Return a cleaned version of pasted Gherkin text.

        Normalizes newlines, strips BOM/zero-width characters, removes a pair
        of outer Markdown code fences when present, and trims trailing spaces so
        copy/paste from chat tools does not pollute stored scenarios.

        Args:
            value: Raw user input coming from the textarea.

        Returns:
            The normalized scenario text ready for structural validation.
        """
        normalized = (
            (value or "")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\ufeff", "")
            .replace("\u200b", "")
            .strip()
        )
        if not normalized:
            return ""

        fence_lines = normalized.split("\n")
        if (
            len(fence_lines) >= 2
            and fence_lines[0].strip().startswith("```")
            and fence_lines[-1].strip() == "```"
        ):
            normalized = "\n".join(fence_lines[1:-1]).strip()

        return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()

    def clean_gherkin_text(self) -> str:
        """Normalize the optional pasted Gherkin text.

        The field intentionally accepts imperfect or mixed content pasted from
        LLM chats and external editors. The only transformation performed here
        is newline/fence cleanup so the stored text stays readable and stable.

        Returns:
            The normalized Gherkin text, or an empty string when omitted.
        """
        return self._normalize_gherkin_text(
            self.cleaned_data.get("gherkin_text", "")
        )




