/* ==========================================================================
   TestCanvas · Shared Cytoscape node highlight helper

   Single source of truth for the "spotlight a node" behaviour shared by the
   map editor (map_editor.js) and the traceability graph (traceability.js).

   It exposes, under the `window.TestCanvasGraph` namespace:
     - HIGHLIGHT_CLASS: the CSS class applied to the highlighted node.
     - HIGHLIGHT_STYLE: a Cytoscape style rule (best-effort fallback) to be
       spread into each instance's `style` array so the class renders a red
       accent. The authoritative highlight is applied as inline element styles
       by `highlightNode`, which always win over stylesheet rules regardless of
       selector specificity (e.g. the coverage `is_complete` rules).
     - highlightNode(cy, nodeId, options): add the class + inline highlight
       styles to a node and, by default, centre the viewport on it.

   The highlight is purely presentational and runtime-only: it is never written
   into `graph_data`, so it is never persisted on save. Centralising it here
   means the look (border + halo) and the behaviour live in ONE place and stay
   consistent across both graphs.
   ========================================================================== */
(function (global) {
    'use strict';

    // Class toggled on the highlighted node. Shared so callers can also remove
    // it (e.g. to clear a previous highlight) without hardcoding the string.
    const HIGHLIGHT_CLASS = 'uid-highlight';

    // Cytoscape style rule for the highlight class: a thin red border plus a
    // soft red halo (overlay). This is a best-effort fallback shared by both
    // graphs; the authoritative highlight is applied as inline element styles in
    // ``highlightNode`` (inline styles always beat stylesheet rules in Cytoscape,
    // regardless of selector specificity). Spread this object into each instance's
    // ``style`` array, kept last for readability.
    const HIGHLIGHT_STYLE = {
        selector: 'node.' + HIGHLIGHT_CLASS,
        style: {
            'border-width': 4,
            'border-color': '#dc2626',
            'border-style': 'solid',
            // Soft red halo around the node for an elegant, non-intrusive accent.
            'overlay-color': '#dc2626',
            'overlay-opacity': 0.12,
            'overlay-padding': 8
        }
    };

    /**
     * Highlight a single node in a Cytoscape graph by its id.
     *
     * Adds the shared highlight class to the matching node and, unless disabled,
     * smoothly centres the viewport on it so it is immediately visible. The
     * highlight is permanent for the session (no timeout) and never persisted.
     * It is a safe no-op when `cy`/`nodeId` are missing or the node is not in
     * this graph (e.g. a node that was never saved).
     *
     * @param {Object} cy The Cytoscape instance to operate on.
     * @param {string} nodeId The id of the node to highlight (Cytoscape id).
     * @param {Object} [options] Optional behaviour flags.
     * @param {boolean} [options.center=true] Centre the viewport on the node.
     * @param {number} [options.duration=400] Centring animation duration (ms).
     * @returns {boolean} True if a node was found and highlighted, else false.
     */
    function highlightNode(cy, nodeId, options) {
        if (!cy || !nodeId) return false;
        const opts = options || {};
        const node = cy.getElementById(nodeId);
        if (node.empty()) return false;  // node not in this graph (e.g. never saved)

        node.addClass(HIGHLIGHT_CLASS);

        // Apply the highlight look as INLINE element styles too. In Cytoscape an
        // element's inline style always wins over any stylesheet rule regardless
        // of selector specificity, so this guarantees the red border/halo shows
        // even on nodes already styled by higher-specificity rules (e.g. the
        // coverage rules `node[is_complete="true"]` which also set the border).
        node.style({
            'border-width': 4,
            'border-color': '#dc2626',
            'border-style': 'solid',
            'overlay-color': '#dc2626',
            'overlay-opacity': 0.12,
            'overlay-padding': 8
        });

        // Centre on the highlighted node without changing the zoom level.
        if (opts.center !== false) {
            cy.animate(
                { center: { eles: node } },
                { duration: typeof opts.duration === 'number' ? opts.duration : 400 }
            );
        }
        return true;
    }

    // Publish the helper on a single global namespace so both page scripts can
    // reuse it without a module bundler.
    global.TestCanvasGraph = global.TestCanvasGraph || {};
    global.TestCanvasGraph.HIGHLIGHT_CLASS = HIGHLIGHT_CLASS;
    global.TestCanvasGraph.HIGHLIGHT_STYLE = HIGHLIGHT_STYLE;
    global.TestCanvasGraph.highlightNode = highlightNode;
})(window);

