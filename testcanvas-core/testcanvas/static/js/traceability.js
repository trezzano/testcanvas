/* ==========================================================================
   TestCanvas · Traceability graph (US -> AC)

   The view (flow_node_traceability) does all the data shaping and hands us a
   ready-to-use Cytoscape `elements` array via `window.TRACEABILITY_CONFIG`:

       { elements: [ { data: { id, label, type, code, detail_url } }, ... ] }

   Node `type` is one of "us" | "ac". Edges carry a `kind` of "decompose"
   (US -> AC). This script only draws the graph and wires a few interactions:
   hover focus + tooltip and a tap that opens the shared, server-rendered detail
   modal (loaded on demand via HTMX from each node's `detail_url`). No parsing,
   no DOM building. Test execution artefacts live in the
   testcanvas_test_execution plugin.
   ========================================================================== */
(function () {
    'use strict';

    const CONFIG = window.TRACEABILITY_CONFIG || {};
    const ELEMENTS = CONFIG.elements || [];

    // Nothing to draw: the template already shows the empty state.
    if (!ELEMENTS.length) return;

    // Graph orientation: 'horizontal' reads as US|AC columns (left->right),
    // 'vertical' stacks the same bands top->bottom (US on top, AC below).
    // Switching orientation is a genuine UI interaction on the Cytoscape widget,
    // so it lives in JS; we remember the choice per session so it survives page
    // navigations just like the viewport does.
    const ORIENTATION_KEY = 'traceability-orientation';
    // First-load framing should feel elegant: centered, with visible breathing
    // room around the diagram, and never so zoomed-in that a handful of nodes
    // occupy the whole canvas.
    const INITIAL_FIT_PADDING = 110;
    const MAX_INITIAL_FIT_ZOOM = 1.0;
    // Fixed distance between the two bands (US ↔ AC). Mirrors the compact spacing
    // the map editor gets from its hierarchical layout: the gap does NOT scale
    // with the container, so a handful of nodes stays clustered and centered
    // instead of being spread across the whole page (which would make even a
    // small diagram look full-screen once fitted).
    const BAND_GAP = 340;
    let orientation = sessionStorage.getItem(ORIENTATION_KEY) || 'horizontal';

    // Build the elements with a preset position for the active orientation.
    const positionedElements = withPositions(orientation);

    const cy = cytoscape({
        container: document.getElementById('cy'),
        elements: positionedElements,
        style: [
            { selector: 'node', style: {
                'font-family': 'JetBrains Mono, monospace', 'font-size': 10, 'color': '#1e293b',
                'text-wrap': 'wrap', 'text-max-width': '100px', 'text-valign': 'center', 'text-halign': 'center',
                'label': 'data(label)', 'border-width': 2,
            }},
            { selector: 'node[type="us"]', style: {
                'shape': 'round-rectangle', 'background-color': '#ede9fe', 'border-color': '#7c3aed',
                'color': '#3b0764', 'width': 150, 'height': 50, 'font-weight': 700, 'font-size': 11,
            }},
            { selector: 'node[type="ac"]', style: {
                'shape': 'ellipse', 'background-color': '#e0e7ff', 'border-color': '#6366f1',
                'color': '#312e81', 'width': 78, 'height': 78,
            }},
            { selector: 'edge[kind="decompose"]', style: {
                'width': 2, 'line-color': '#c4b5fd', 'target-arrow-color': '#c4b5fd',
                'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
            }},
            { selector: '.faded', style: { 'opacity': 0.45 } },
            { selector: '.highlighted', style: { 'opacity': 1 } },
        ],
        // Preset layout: we assign each node an explicit position (see
        // `withColumnPositions`) so the graph reads as US | AC | TC columns.
        // We do NOT auto-fit here: a saved viewport (if any) is restored below,
        // otherwise we fit the whole graph manually on the first visit.
        layout: { name: 'preset', fit: false, padding: 30 },
        minZoom: 0.2, maxZoom: 2.5,
        userZoomingEnabled: true,    // free zoom in/out (wheel, pinch, buttons)
        userPanningEnabled: true,    // free panning to navigate large graphs
        boxSelectionEnabled: false,
        autoungrabify: true,         // view-only graph: nodes can't be dragged
    });


    // Restore the previous zoom/pan if the user already navigated this graph,
    // otherwise fit the whole graph into view on the first visit.
    persistViewport(cy);

    wireInteractions(cy);
    wireOrientationToggle(cy);

    /**
     * Keep the graph viewport (zoom + pan) stable across full page reloads.
     *
     * The page is rebuilt from scratch every time the user edits a node and
     * comes back, which would otherwise reset zoom and position. We store the
     * viewport in ``sessionStorage`` (keyed by Flow Node id) and restore it on
     * load; when there is nothing saved we apply a softer first-load fit that
     * keeps small graphs centered without letting them balloon to full screen.
     *
     * Args:
     *     cy: The Cytoscape instance to observe and control.
     */
    function persistViewport(cy) {
        // Key the saved state per Flow Node so each one keeps its own viewport.
        const key = 'traceability-viewport:' + (CONFIG.node_id || location.pathname);

        function saveViewport() {
            sessionStorage.setItem(key, JSON.stringify({ zoom: cy.zoom(), pan: cy.pan() }));
        }

        function restoreViewport() {
            const raw = sessionStorage.getItem(key);
            if (!raw) return false;            // nothing saved -> caller will fit
            try {
                const v = JSON.parse(raw);
                cy.zoom(v.zoom);
                cy.pan(v.pan);
                return true;
            } catch (e) {
                return false;                  // corrupted state -> fall back to fit
            }
        }

        // First visit (or unreadable state): use a softer framing with a larger
        // padding and a zoom ceiling, so even tiny diagrams keep some elegant
        // white space instead of expanding edge-to-edge.
        if (!restoreViewport()) fitGraphInitially(cy);

        // Persist on every zoom/pan, debounced to avoid excessive writes.
        let saveTimer = null;
        cy.on('zoom pan', () => {
            clearTimeout(saveTimer);
            saveTimer = setTimeout(saveViewport, 150);
        });
    }

    /**
     * Center the whole graph with an intentionally airy first-load framing.
     *
     * Cytoscape's raw ``fit`` tries to fill as much of the viewport as it can,
     * which makes very small diagrams look oversized. We fit first, then cap the
     * resulting zoom at a natural scale and re-center the graph.
     *
     * Args:
     *     cy: The Cytoscape instance to frame.
     */
    function fitGraphInitially(cy) {
        cy.fit(cy.elements(), INITIAL_FIT_PADDING);
        if (cy.zoom() > MAX_INITIAL_FIT_ZOOM) {
            cy.zoom(MAX_INITIAL_FIT_ZOOM);
            cy.center(cy.elements());
        }
    }


    /**
     * Compute a preset position for every node for the given orientation.
     *
     * Nodes are grouped into two bands by ``type`` (us | ac). In ``horizontal``
     * mode the bands are vertical columns; in ``vertical`` mode they are
     * horizontal rows. The two bands are separated by a FIXED ``BAND_GAP`` and
     * centered in the container, so a graph with few nodes stays compact and
     * centered (reduced) instead of stretching across the whole page. Siblings
     * inside a band are evenly spaced and centered.
     *
     * Args:
     *     orientation: Either ``'horizontal'`` or ``'vertical'``.
     *
     * Returns:
     *     An object mapping each node id to its ``{ x, y }`` position.
     */
    function computePositions(orientation) {
        const box = document.getElementById('cy');
        const width = box.clientWidth || 1200;
        const height = box.clientHeight || 600;
        const siblingGap = 110;   // spacing between nodes sharing the same band

        // Group node ids by type, keeping their original order.
        const bands = { us: [], ac: [] };
        ELEMENTS.forEach(el => {
            const type = el.data && el.data.type;
            if (type && bands[type]) bands[type].push(el.data.id);
        });

        const vertical = orientation === 'vertical';
        // Band anchor along the "reading" axis (X when horizontal, Y when
        // vertical). Both bands sit a fixed BAND_GAP apart, centered on the
        // container, so the diagram never spreads out with the viewport size.
        const centerX = width / 2;
        const centerY = height / 2;
        const bandPos = vertical
            ? { us: centerY - BAND_GAP / 2, ac: centerY + BAND_GAP / 2 }
            : { us: centerX - BAND_GAP / 2, ac: centerX + BAND_GAP / 2 };

        const positions = {};
        Object.keys(bands).forEach(type => {
            const ids = bands[type];
            const n = ids.length;
            ids.forEach((id, i) => {
                const offset = (i - (n - 1) / 2) * siblingGap;
                positions[id] = vertical
                    ? { x: centerX + offset, y: bandPos[type] }
                    : { x: bandPos[type], y: centerY + offset };
            });
        });
        return positions;
    }

    /**
     * Return a copy of the elements with a preset ``position`` on every node for
     * the given orientation. Edges are passed through untouched.
     *
     * Args:
     *     orientation: Either ``'horizontal'`` or ``'vertical'``.
     */
    function withPositions(orientation) {
        const positions = computePositions(orientation);
        return ELEMENTS.map(el => {
            const id = el.data && el.data.id;
            if (id && positions[id]) return Object.assign({}, el, { position: positions[id] });
            return el;   // edges (no position needed)
        });
    }

    /**
     * Reposition the existing graph to a new orientation and refit the view.
     *
     * The nodes stay view-only (``autoungrabify``) but are no longer locked, so
     * a preset layout can move them to their new band positions. The result is
     * animated and reframed, and the choice is saved per session so it persists
     * across page navigations.
     *
     * Args:
     *     cy: The Cytoscape instance to reposition.
     *     newOrientation: Either ``'horizontal'`` or ``'vertical'``.
     */
    function applyOrientation(cy, newOrientation) {
        orientation = newOrientation;
        sessionStorage.setItem(ORIENTATION_KEY, orientation);

        const positions = computePositions(orientation);
        // Preset layout with an explicit position provider: it moves every node
        // to its new band and refits the whole graph into view.
        cy.layout({
            name: 'preset',
            positions: node => positions[node.id()],
            fit: true,
            padding: 30,
            animate: true,
            animationDuration: 300,
        }).run();

        updateToggleUI(orientation);
    }

    /** Wire the orientation toggle buttons and reflect the active choice. */
    function wireOrientationToggle(cy) {
        const buttons = document.querySelectorAll('.layout-btn');
        if (!buttons.length) return;
        buttons.forEach(btn => {
            btn.addEventListener('click', () => applyOrientation(cy, btn.dataset.orientation));
        });
        updateToggleUI(orientation);
    }

    /** Highlight the button matching the active orientation. */
    function updateToggleUI(active) {
        document.querySelectorAll('.layout-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.orientation === active);
        });
    }

    /**
     * Wire the minimal graph interactions: hover focus + tooltip and a
     * tap-to-open detail modal. The detail card itself is rendered by the
     * server (shared HTMX partial) and only loaded on demand, so this script
     * builds no DOM and holds no business logic.
     */
    function wireInteractions(cy) {
        let selectedNode = null;
        const graphWrap = document.querySelector('.graph-wrap');
        const tooltip = document.getElementById('tooltip');
        const tooltipId = tooltip.querySelector('.t-id');
        const tooltipDesc = tooltip.querySelector('.t-desc');

        function clearFocus() { cy.elements().removeClass('faded highlighted'); }
        function focusRelations(node) {
            cy.elements().addClass('faded').removeClass('highlighted');
            node.closedNeighborhood().removeClass('faded').addClass('highlighted');
        }
        function hideTooltip() { tooltip.style.display = 'none'; }

        function showTooltip(node, evt) {
            tooltipId.textContent = node.data('code') || node.data('id');
            tooltipDesc.textContent = 'Click for details';
            const rect = graphWrap.getBoundingClientRect();
            const oe = evt.originalEvent;
            const px = (oe ? oe.clientX : rect.left + evt.renderedPosition.x) - rect.left + 16;
            const py = (oe ? oe.clientY : rect.top + evt.renderedPosition.y) - rect.top + 16;
            tooltip.style.display = 'block';
            tooltip.style.left = Math.max(8, px) + 'px';
            tooltip.style.top = Math.max(8, py) + 'px';
        }

        cy.on('mouseover', 'node', evt => { if (!selectedNode) { focusRelations(evt.target); showTooltip(evt.target, evt); } });
        cy.on('mousemove', 'node', evt => { if (tooltip.style.display === 'block') showTooltip(evt.target, evt); });
        cy.on('mouseout', 'node', () => { hideTooltip(); if (!selectedNode) clearFocus(); });
        cy.on('tap', 'node', evt => { selectedNode = evt.target; focusRelations(selectedNode); hideTooltip(); openDetail(selectedNode); });
        cy.on('tap', evt => { if (evt.target === cy) { selectedNode = null; clearFocus(); hideTooltip(); } });
    }

    /**
     * Load the tapped node's detail card into the shared detail sidebar.
     *
     * The node carries a ``detail_url`` pointing at the server-rendered HTMX
     * partial (US / AC / TC). We fetch it into the sidebar body; detail_sidebar.js
     * slides the panel in automatically once the swap lands — no card is built
     * here and no modal is involved.
     *
     * Args:
     *     node: The tapped Cytoscape node.
     */
    function openDetail(node) {
        const url = node.data('detail_url');
        if (!url || !window.htmx) return;
        // The sidebar controller opens the panel on htmx:afterSwap of the body.
        htmx.ajax('GET', url, { target: '#detail-sidebar-body', swap: 'innerHTML' });
    }
})();

