/*
 * Rich-text description editor for the ApplicationMapsCollection form.
 *
 * Initialises a Quill editor bound to the visible container and keeps the
 * hidden Django textarea (#collection-description) in sync so the HTML is
 * submitted with the form. Mirrors the approach used in the map editor.
 */
(function () {
    "use strict";

    // Hidden textarea backing the Django form field.
    var textarea = document.getElementById("collection-description");
    var editorEl = document.getElementById("collection-description-editor");
    var form = document.getElementById("collection-form");

    if (!textarea || !editorEl || !form || typeof Quill === "undefined") {
        return;
    }

    // Create the Quill editor with a compact toolbar.
    var quill = new Quill(editorEl, {
        theme: "snow",
        placeholder: "Describe this collection...",
        modules: {
            toolbar: [
                [{ header: [1, 2, 3, false] }],
                ["bold", "italic", "underline"],
                [{ list: "ordered" }, { list: "bullet" }],
                ["link", "clean"]
            ]
        }
    });

    // Preload any existing HTML (edit mode) from the textarea into the editor.
    if (textarea.value) {
        quill.clipboard.dangerouslyPasteHTML(textarea.value);
    }

    // Before submitting, copy the editor HTML back into the hidden textarea.
    form.addEventListener("submit", function () {
        var html = quill.root.innerHTML;
        // Treat an empty editor as an empty string instead of "<p><br></p>".
        textarea.value = quill.getText().trim() ? html : "";
    });
})();

