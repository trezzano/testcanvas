/* ==========================================================================
   TestCanvas · Traceability graph logic (US -> AC -> TC)
   Reads runtime config from `window.TRACEABILITY_CONFIG` injected by the template:
       { graphData, editUrls: { us, ac, tc, acManage } }
   Backend schema:
     {
       "user_stories":        [{ id, code, name, description, acceptance_criteria:[AC_id,...] }],
       "acceptance_criteria": [{ id, code, description }],
       "test_cases":          [{ id, code, name, status, verifies:[AC_id,...] }]
     }
   ========================================================================== */
(function () {
    'use strict';

    const CONFIG = window.TRACEABILITY_CONFIG || {};
    const GRAPH_DATA = CONFIG.graphData || {};
    const EDIT_URLS = CONFIG.editUrls || {};

    function editUrlFor(node) {
        const type = node.data('type');
        if (type !== 'us' && type !== 'ac' && type !== 'tc') return null;
        // Node ids look like "US_<pk>" / "AC_<pk>" / "TC_<pk>".
        const pk = String(node.data('id')).split('_')[1];
        if (!pk) return null;
        return EDIT_URLS[type].replace('/0/', '/' + pk + '/');
    }

    function buildParsed(data) {
        const nodes = { us: {}, ac: {}, tc: {} };
        const edges = [];

        (data.user_stories || []).forEach(us => {
            nodes.us[us.id] = { id: us.id, code: us.code || '', label: us.name || '', description: us.description || '' };
            (us.acceptance_criteria || []).forEach(acId => {
                if (!nodes.ac[acId]) nodes.ac[acId] = { id: acId, code: '', description: '' };
                edges.push({ source: us.id, target: acId, kind: 'decompose' });
            });
        });

        (data.acceptance_criteria || []).forEach(ac => {
            nodes.ac[ac.id] = { id: ac.id, code: ac.code || '', description: ac.description || '' };
        });

        (data.test_cases || []).forEach(tc => {
            nodes.tc[tc.id] = { id: tc.id, code: tc.code || '', label: tc.name || '', status: tc.status || '' };
            (tc.verifies || []).forEach(acId => {
                if (!nodes.ac[acId]) nodes.ac[acId] = { id: acId, code: '', description: '' };
                edges.push({ source: tc.id, target: acId, kind: 'verify' });
            });
        });

        return { nodes, edges };
    }

    function buildElements(parsed) {
        const els = [];
        const coverage = {};
        Object.values(parsed.nodes.ac).forEach(a => coverage[a.id] = 0);
        parsed.edges.forEach(e => { if (e.kind === 'verify') coverage[e.target] = (coverage[e.target] || 0) + 1; });

        // Three-column layout anchored to the real lane centers US | AC | TC.
        // The lanes are three equal flex columns (1/3 each), so their centers fall
        // at 1/6, 3/6 and 5/6 of the width. Nodes are placed in screen coordinates
        // with fit disabled, so alignment holds even when a column is empty.
        const cyBox = document.getElementById('cy');
        const CW = cyBox.clientWidth || 1200;
        const CH = cyBox.clientHeight || 600;
        const COL_X = { us: CW * (1 / 6), ac: CW * (3 / 6), tc: CW * (5 / 6) };
        const ROW_GAP = 110;

        function placeColumn(nodesArray, type) {
            const positions = {};
            const n = nodesArray.length;
            nodesArray.forEach((node, i) => {
                positions[node.id] = { x: COL_X[type], y: CH / 2 + (i - (n - 1) / 2) * ROW_GAP };
            });
            return positions;
        }

        const usNodes = Object.values(parsed.nodes.us);
        const acNodes = Object.values(parsed.nodes.ac).sort((a, b) => a.id.localeCompare(b.id));
        const tcNodes = Object.values(parsed.nodes.tc).sort((a, b) => a.id.localeCompare(b.id));
        const posUS = placeColumn(usNodes, 'us');
        const posAC = placeColumn(acNodes, 'ac');
        const posTC = placeColumn(tcNodes, 'tc');

        usNodes.forEach(n =>
            els.push({ data: { id: n.id, label: (n.code || n.id) + (n.label ? '\n' + n.label : ''), type: 'us', code: n.code, full: n.description }, position: posUS[n.id] })
        );
        acNodes.forEach(n => {
            const covered = (coverage[n.id] || 0) > 0;
            els.push({ data: { id: n.id, label: n.code || n.id, type: 'ac', covered, covCount: coverage[n.id] || 0, code: n.code, full: n.description }, position: posAC[n.id] });
        });
        tcNodes.forEach(n =>
            els.push({ data: { id: n.id, label: n.code || n.id, type: 'tc', code: n.code, status: n.status, full: n.label }, position: posTC[n.id] })
        );
        parsed.edges.forEach((e, i) =>
            els.push({ data: { id: 'e' + i, source: e.source, target: e.target, kind: e.kind } })
        );
        return { els, coverage, parsed };
    }

    const parsed = buildParsed(GRAPH_DATA);
    const { els, coverage } = buildElements(parsed);

    // NOTE: Stats counters and the lane "Modifica" / "Add" button states
    // (enabled/disabled and their target URLs) are rendered server-side by the
    // Django template. This script only draws the graph and its interactions.

    // --- Coverage list ---
    const covList = document.getElementById('coverage-list');
    Object.keys(parsed.nodes.ac).sort().forEach(id => {
        const c = coverage[id] || 0;
        const ac = parsed.nodes.ac[id];
        const row = document.createElement('div');
        row.className = 'cov-row';
        row.innerHTML = `<span>${ac.code || id}</span>
            <span class="badge ${c > 0 ? 'ok' : 'no'}">${c > 0 ? c + ' TC' : 'scoperto'}</span>`;
        covList.appendChild(row);
    });

    document.getElementById('empty-state').style.display = els.length ? 'none' : 'flex';

    let cy = null;
    if (els.length) {
        cy = cytoscape({
            container: document.getElementById('cy'),
            elements: els,
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
                { selector: 'node[type="ac"][?covered]', style: {
                    'shape': 'ellipse', 'background-color': '#d1fae5', 'border-color': '#059669',
                    'color': '#064e3b', 'width': 78, 'height': 78,
                }},
                { selector: 'node[type="ac"][!covered]', style: {
                    'shape': 'ellipse', 'background-color': '#fee2e2', 'border-color': '#ef4444',
                    'color': '#7f1d1d', 'width': 78, 'height': 78,
                }},
                { selector: 'node[type="tc"]', style: {
                    'shape': 'round-rectangle', 'background-color': '#e0f2fe', 'border-color': '#0284c7',
                    'border-style': 'dashed', 'color': '#0c4a6e', 'width': 110, 'height': 42,
                }},
                { selector: 'edge[kind="decompose"]', style: {
                    'width': 2, 'line-color': '#c4b5fd', 'target-arrow-color': '#c4b5fd',
                    'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
                }},
                { selector: 'edge[kind="verify"]', style: {
                    'width': 1.8, 'line-color': '#6ee7b7', 'target-arrow-color': '#6ee7b7',
                    'target-arrow-shape': 'triangle', 'line-style': 'dashed', 'curve-style': 'bezier', 'opacity': 0.9,
                }},
                { selector: '.faded', style: { 'opacity': 0.45 } },
                { selector: '.highlighted', style: { 'opacity': 1 } },
            ],
            layout: { name: 'preset', fit: false, padding: 0 },
            zoom: 1,
            pan: { x: 0, y: 0 },
            minZoom: 0.3, maxZoom: 2.5, wheelSensitivity: 0.25,
            // View-only graph: prevent users from dragging/repositioning nodes.
            autoungrabify: true,
            autolock: true,
        });

        // Belt-and-suspenders: explicitly lock every node so it cannot be
        // dragged or repositioned, regardless of how it was created.
        cy.nodes().ungrabify().lock();

        wireInteractions(cy);
    }

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
            tooltipDesc.textContent = node.data('full') || 'Nessuna descrizione disponibile.';
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
        cy.on('tap', 'node', evt => { selectedNode = evt.target; focusRelations(selectedNode); hideTooltip(); showCard(selectedNode); });
        cy.on('tap', evt => { if (evt.target === cy) { selectedNode = null; clearFocus(); hideTooltip(); hideCard(); } });

        document.getElementById('nd-close').onclick = () => { selectedNode = null; clearFocus(); hideCard(); };
    }

    function hideCard() { document.getElementById('node-detail').style.display = 'none'; }

    function showCard(node) {
        const type = node.data('type');
        const typeLabel = { us: 'User Story', ac: 'Acceptance Criteria', tc: 'Test Case' }[type];
        const badge = document.getElementById('nd-badge');
        badge.textContent = typeLabel;
        badge.className = 'type-' + (type === 'ac' ? (node.data('covered') ? 'ac-covered' : 'ac-uncovered') : type);

        document.getElementById('nd-id').textContent = node.data('id');
        document.getElementById('nd-code').textContent = node.data('code') || '';
        document.getElementById('nd-desc').textContent = node.data('full') || 'Nessuna descrizione disponibile.';

        let meta = '';
        if (type === 'ac') meta = node.data('covered') ? `Coperto da ${node.data('covCount')} test case` : 'Nessun test case associato';
        else if (type === 'tc' && node.data('status')) meta = 'Stato: ' + node.data('status');
        document.getElementById('nd-meta').textContent = meta;

        const editLink = document.getElementById('nd-edit');
        const editUrl = editUrlFor(node);
        if (editUrl) {
            const editLabels = { us: 'User Story', ac: 'Acceptance Criterion', tc: 'Test Case' };
            editLink.href = editUrl;
            editLink.textContent = '✎ Edit ' + (editLabels[type] || '');
            editLink.style.display = 'block';
            // Cytoscape's canvas can swallow the anchor click, so navigate explicitly.
            editLink.onclick = (e) => { e.preventDefault(); e.stopPropagation(); window.location.href = editUrl; };
        } else {
            editLink.style.display = 'none';
            editLink.onclick = null;
        }

        document.getElementById('node-detail').style.display = 'block';
    }
})();

