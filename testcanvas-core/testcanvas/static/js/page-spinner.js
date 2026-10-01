/**
 * Full-Page Blocking Spinner Controller
 *
 * Manages a full-page overlay spinner that blocks user interaction during
 * page navigation. Separate from the HTMX corner spinner for partial updates.
 *
 * Usage:
 *   Add class "full-page-spinner" to any link:
 *     <a href="/page" class="full-page-spinner">Go to page</a>
 *
 * UX design notes:
 *   - A short SHOW_DELAY suppresses the overlay on fast navigations, so quick
 *     page loads never flash the spinner (mirrors the HTMX spinner behavior).
 *   - Navigation happens natively; the delayed reveal decides whether the
 *     overlay is actually shown, so no artificial latency is added.
 *   - A safety timeout force-hides the overlay if a navigation stalls.
 *   - ``pageshow`` clears the overlay when a page is restored from the
 *     browser Back/Forward cache (bfcache).
 *
 * @module page-spinner
 */

(function () {
    'use strict';

    // Configuration constants
    var CONFIG = {
        OVERLAY_ID: 'page-spinner-overlay',
        ACTIVE_CLASS: 'is-active',
        BODY_ACTIVE_CLASS: 'page-spinner-active',
        LINK_CLASS: 'full-page-spinner',
        SHOW_DELAY_MS: 140,        // Anti-flicker: reveal only if load is slow.
        SAFETY_TIMEOUT_MS: 30000,  // Force-hide if navigation stalls (30s).
    };

    /**
     * Cached references to DOM elements.
     *
     * @type {Object}
     */
    var refs = {
        overlay: null,
    };

    /**
     * State tracking for active timers.
     *
     * @type {Object}
     */
    var timers = {
        show: null,    // Pending delayed reveal (anti-flicker window).
        safety: null,  // Watchdog against a stalled navigation.
    };

    /**
     * Initialize the module: cache DOM refs and bind event listeners.
     *
     * Must be called after DOM is ready (e.g. at script end in base.html).
     */
    function init() {
        refs.overlay = document.getElementById(CONFIG.OVERLAY_ID);
        if (!refs.overlay) {
            return;
        }

        // Bind click handlers to all links with the opt-in class (capture
        // phase so we intercept before other handlers).
        document.addEventListener('click', handleLinkClick, true);

        // Hide the spinner whenever this page becomes visible. This covers the
        // browser Back/Forward cache (bfcache): when the user navigates back,
        // the previous page can be restored from cache WITH the spinner still
        // on screen, so we must clear it. We do NOT bind to ``beforeunload``
        // because that fires as the new navigation starts and would hide the
        // spinner while the next page is still loading.
        window.addEventListener('pageshow', hide);
    }

    /**
     * Request the spinner to appear after a short anti-flicker delay.
     *
     * Navigation proceeds natively; this only schedules the reveal so that fast
     * page loads (which unload this document before the delay elapses) never
     * flash the overlay. Also arms the safety watchdog.
     */
    function show() {
        if (!refs.overlay) return;

        // Schedule the delayed reveal (anti-flicker). If the page unloads
        // before this fires, the spinner never appears.
        if (timers.show) window.clearTimeout(timers.show);
        timers.show = window.setTimeout(reveal, CONFIG.SHOW_DELAY_MS);

        // Arm safety timeout: if navigation takes >30s, auto-hide.
        if (timers.safety) window.clearTimeout(timers.safety);
        timers.safety = window.setTimeout(hide, CONFIG.SAFETY_TIMEOUT_MS);
    }

    /**
     * Reveal the overlay now (called after the anti-flicker delay elapses).
     */
    function reveal() {
        timers.show = null;
        if (!refs.overlay) return;
        refs.overlay.classList.add(CONFIG.ACTIVE_CLASS);
        document.body.classList.add(CONFIG.BODY_ACTIVE_CLASS);
    }

    /**
     * Hide the full-page spinner overlay and restore interaction.
     *
     * Removes the active classes, re-enables scrolling and clears any pending
     * timers (both the delayed reveal and the safety watchdog).
     */
    function hide() {
        if (!refs.overlay) return;

        if (timers.show) { window.clearTimeout(timers.show); timers.show = null; }
        if (timers.safety) { window.clearTimeout(timers.safety); timers.safety = null; }

        refs.overlay.classList.remove(CONFIG.ACTIVE_CLASS);
        document.body.classList.remove(CONFIG.BODY_ACTIVE_CLASS);
    }

    /**
     * Handle click events on links with the opt-in "full-page-spinner" class.
     *
     * Ignores modified clicks (new tab / download) and non-navigating links,
     * then lets the browser navigate normally while scheduling the delayed
     * spinner reveal.
     *
     * @param {MouseEvent} event - The click event.
     */
    function handleLinkClick(event) {
        // Respect new-tab / new-window / download intents: do not show a
        // full-page spinner when the current page is NOT going to navigate.
        if (event.defaultPrevented) return;
        if (event.button !== 0) return;  // Only react to the primary button.
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

        // Walk up from the clicked node to the nearest anchor.
        var target = event.target;
        while (target && target.tagName !== 'A') {
            target = target.parentElement;
        }
        if (!target || !target.classList.contains(CONFIG.LINK_CLASS)) return;

        // Skip links that do not trigger a same-tab navigation.
        if (target.target && target.target !== '_self') return;  // e.g. _blank
        if (target.hasAttribute('download')) return;

        var href = target.getAttribute('href');
        if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) {
            return;  // In-page anchor or JS pseudo-link: nothing to load.
        }

        // Let the browser perform the navigation normally; just schedule the
        // (possibly suppressed) spinner reveal. No preventDefault, no delay.
        show();
    }

    // Initialize on DOM ready (at script execution time in base.html)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose a minimal public API for manual control (e.g. before an async op).
    window.PageSpinner = {
        show: show,
        hide: hide,
    };
})();
