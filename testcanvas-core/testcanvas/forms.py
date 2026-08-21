from django import forms
from django.utils.translation import gettext_lazy as _

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
    keeps in sync. ``background_color`` is chosen from a fixed palette of six
    predefined colors (rendered as clickable swatches). The optional ``parent``
    field lets the collection be nested under another one, forming the
    folder/sub-folder tree.
    """

    # Compact palette of six clearly distinct, fresh/modern accent colors. Hues
    # are spread across the wheel so adjacent swatches never look alike. Values
    # are the hex codes stored on the model; labels stay human-readable.
    COLOR_PALETTE = [
        ("#ef4444", _("Red")),
        ("#f97316", _("Orange")),
        ("#22c55e", _("Green")),
        ("#06b6d4", _("Cyan")),
        ("#6366f1", _("Indigo")),
        ("#ec4899", _("Pink")),
    ]

    # Replace the free color picker with a constrained palette. RadioSelect keeps
    # a single choice; the template renders each option as a colored swatch.
    background_color = forms.ChoiceField(
        choices=COLOR_PALETTE,
        initial=COLOR_PALETTE[0][0],
        widget=forms.RadioSelect(attrs={"class": "color-palette"}),
        label=_("Background color"),
    )

    class Meta:
        model = ApplicationMapsCollection
        fields = ("title", "description", "background_color", "parent")
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
            # Parent folder selector; "---------" (empty) keeps the collection
            # at the top level.
            "parent": forms.Select(attrs={
                "class": "field-input",
            }),
        }
        labels = {
            "parent": _("Parent collection"),
        }

    def __init__(self, *args, **kwargs):
        """Restrict the ``parent`` choices to avoid self-references and cycles.

        When editing an existing collection, the instance itself and all of its
        descendants are removed from the ``parent`` dropdown so the UI cannot
        even offer a choice that would create a cycle. ``clean_parent`` still
        enforces the rule server-side as a safety net.
        """
        super().__init__(*args, **kwargs)

        queryset = ApplicationMapsCollection.objects.all()
        if self.instance and self.instance.pk:
            # Exclude self and every descendant: none of them can be the parent.
            forbidden_ids = [self.instance.pk] + [
                descendant.pk for descendant in self.instance.get_descendants()
            ]
            queryset = queryset.exclude(pk__in=forbidden_ids)

        self.fields["parent"].queryset = queryset.order_by("title")
        self.fields["parent"].required = False
        self.fields["parent"].empty_label = _("— No parent (top level) —")

    def clean_parent(self):
        """Reject a ``parent`` that is the instance itself or one of its descendants.

        Returns:
            The validated parent collection, or ``None`` for a root collection.

        Raises:
            forms.ValidationError: If the chosen parent would create a cycle.
        """
        parent = self.cleaned_data.get("parent")
        if parent is None:
            return None

        if self.instance and self.instance.pk:
            if parent.pk == self.instance.pk:
                raise forms.ValidationError(
                    _("A collection cannot be its own parent.")
                )
            if parent.is_descendant_of(self.instance):
                raise forms.ValidationError(
                    _("A collection cannot be moved under its own descendants.")
                )
        return parent


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


class TestCaseForm(forms.ModelForm):
    """ModelForm to create/edit a TestCase bound to an AcceptanceCriterion.

    Exposes the minimal Test Case model: a traceability ``code`` and a free-text
    ``description`` holding steps, data and expected result. Mirrors
    ``AcceptanceCriterionForm`` for a consistent authoring UX.
    """

    class Meta:
        model = TestCase
        fields = ("code", "description")
        widgets = {
            "code": forms.TextInput(attrs={
                "class": "field-input",
                "placeholder": _("e.g. TC-01.1.1"),
            }),
            "description": forms.Textarea(attrs={
                "class": "field-input",
                "rows": 6,
                "placeholder": _("Steps, test data, expected result, or extra context"),
            }),
        }
        labels = {
            "code": _("Code"),
            "description": _("Description"),
        }

