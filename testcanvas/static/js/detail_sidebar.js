/* ==========================================================================
   TestCanvas · Detail sidebar

   Shared, tiny controller for the traceability detail panel (graph + RTM). It
   only shows/hides the panel and wires the close / re-open buttons; the content
   is server-rendered and loaded by HTMX into ``#detail-sidebar-body``.

   The panel opens automatically whenever HTMX finishes swapping a detail card
   into its body, so both entry points stay declarative:
     - RTM table: plain ``hx-get`` links targeting the sidebar body.
     - Graph: traceability.js calls ``htmx.ajax(... target: sidebar body ...)``.

   Exposes ``window.DetailSidebar = { open, close }`` for convenience.
   ========================================================================== */
(function () {
    'use strict';

    const sidebar = document.getElementById('detail-sidebar');
    if (!sidebar) return;

    const body = document.getElementById('detail-sidebar-body');
    const closeBtn = document.getElementById('detail-sidebar-close');
    const reopenBtn = document.getElementById('detail-sidebar-reopen');

    /** Slide the panel in and hide the re-open tab. */
    function open() {
        sidebar.classList.remove('collapsed');
        sidebar.setAttribute('aria-hidden', 'false');
        reopenBtn.classList.add('is-hidden');
    }

    /** Slide the panel out; keep the last content and offer the re-open tab. */
    function close() {
        sidebar.classList.add('collapsed');
        sidebar.setAttribute('aria-hidden', 'true');
        // Only offer to re-open once something has actually been loaded.
        if (body.children.length) reopenBtn.classList.remove('is-hidden');
    }

    /**
     * Copy plain text to the clipboard.
     *
     * Uses the async Clipboard API when available, then falls back to a hidden
     * textarea so HTMX-loaded cards keep working even in non-secure contexts.
     *
     * @param {string} value Text to copy.
     * @returns {Promise<void>} Resolves when the text has been copied.
     */
    async function copyText(value) {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(value);
            return;
        }

        const helper = document.createElement('textarea');
        helper.value = value;
        helper.setAttribute('readonly', 'readonly');
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        helper.style.pointerEvents = 'none';
        document.body.appendChild(helper);
        helper.focus();
        helper.select();
        helper.setSelectionRange(0, helper.value.length);
        document.execCommand('copy');
        document.body.removeChild(helper);
    }

    closeBtn.addEventListener('click', close);
    reopenBtn.addEventListener('click', open);

    // HTMX replaces the sidebar content on every click, so a single delegated
    // listener keeps copy buttons working for User Stories, ACs and Test Cases.
    body.addEventListener('click', async (event) => {
        const button = event.target.closest('.detail-copy-btn');
        if (!button) return;

        const value = (button.dataset.copyText || '').trim();
        if (!value) return;

        const defaultLabel = button.dataset.copyLabel || '📋';
        const successLabel = button.dataset.copySuccessLabel || '✔';

        try {
            await copyText(value);
            button.textContent = successLabel;
            window.setTimeout(() => {
                button.textContent = defaultLabel;
            }, 1500);
        } catch (error) {
            button.textContent = '✕';
            window.setTimeout(() => {
                button.textContent = defaultLabel;
            }, 1500);
            // Keep the failure visible in dev tools without surfacing noisy UI.
            console.error('Could not copy detail UID.', error);
        }
    });

    // Open as soon as a detail card lands in the body (single, shared trigger
    // for both the graph and the RTM table).
    body.addEventListener('htmx:afterSwap', open);

    window.DetailSidebar = { open, close };
})();

