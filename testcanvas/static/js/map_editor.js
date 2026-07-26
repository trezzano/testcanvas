/* ==========================================================================
   TestCanvas · Map editor logic (Cytoscape graph + inspector + HTMX stories)
   Reads runtime config from `window.MAP_EDITOR_CONFIG` injected by the template:
       { graphData, saveUrl, userStoriesUrl }
   ========================================================================== */
(function () {
    'use strict';

    const CONFIG = window.MAP_EDITOR_CONFIG || {};
    const GRAPH_DATA = CONFIG.graphData || { elements: [] };
    const SAVE_URL = CONFIG.saveUrl;
    // Base URL with a placeholder swapped at runtime for the selected node id (HTMX request).
    const USER_STORIES_URL = CONFIG.userStoriesUrl;

    // In-memory rich-text description (HTML). Persisted alongside the graph on Save.
    let mapDescription = CONFIG.description || '';

    const NODE_DEFAULT_COLOR = '#2563eb';
    const EDGE_DEFAULT_COLOR = '#94a3b8';
    // Sub-flow reference nodes get a fixed look (shape/colour are NOT user-editable).
    const SUBFLOW_COLOR = '#7c3aed';
    // Maps that can be referenced as a sub-flow (injected by the template).
    const SUBFLOWS = CONFIG.subflows || [];
    // URL of the map editor with a placeholder pk (0) to build sub-flow links.
    const MAP_EDITOR_URL = CONFIG.mapEditorUrl || '';

    // Node shape presets. Each key maps to the Cytoscape shape used for rendering and,
    // for the semantic presets (Start/End/Condition), the colour that goes with it.
    // `color: null` means "keep whatever colour the node already has".
    const SHAPE_PRESETS = {
        start:     { cyShape: 'round-rectangle', color: '#10b981' }, // green box
        end:       { cyShape: 'round-rectangle', color: '#f59e0b' }, // orange box
        condition: { cyShape: 'diamond',         color: '#facc15' }, // yellow diamond
        squared:   { cyShape: 'round-rectangle', color: null }       // plain square, keep colour
    };

    // Translate a stored node `shape` key into the concrete Cytoscape shape name.
    function cyShapeFor(shapeKey) {
        const preset = SHAPE_PRESETS[shapeKey];
        return preset ? preset.cyShape : 'ellipse';
    }

    // Palette shared by nodes and edges.
    const SWATCH_PALETTE = [
        '#2563eb', '#10b981', '#ef4444', '#f59e0b',
        '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16',
        '#0ea5e9', '#f97316', '#14b8a6', '#a855f7',
        '#1e293b', '#64748b', '#cbd5e1', '#ffffff'
    ];

    function getCsrfToken() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    // Normalise stored NetworkX/Cytoscape data into an elements array for Cytoscape.
    function buildElements(data) {
        if (!data || !data.elements) return [];
        const els = data.elements;
        if (Array.isArray(els)) return els;
        return [].concat(els.nodes || [], els.edges || []);
    }

    let nodeCounter = 0;

    // Decide the initial layout: if the stored nodes already carry positions we must
    // honour them with the 'preset' layout, otherwise we auto-orient the graph
    // top-down (see `runAutoLayout` below) once Cytoscape is ready.
    function hasSavedPositions(data) {
        if (!data || !data.elements) return false;
        const els = data.elements;
        const nodes = Array.isArray(els)
            ? els.filter(e => !(e.data && e.data.source))
            : (els.nodes || []);
        return nodes.length > 0 && nodes.every(
            n => n.position && typeof n.position.x === 'number' && typeof n.position.y === 'number'
        );
    }
    const HAS_SAVED_POSITIONS = hasSavedPositions(GRAPH_DATA);
    // 'preset' keeps stored coordinates; 'grid' is only a placeholder that is
    // immediately replaced by the top-down auto layout for brand-new graphs.
    const INITIAL_LAYOUT = HAS_SAVED_POSITIONS ? 'preset' : 'grid';

    const cy = cytoscape({
        container: document.getElementById('cy'),
        elements: buildElements(GRAPH_DATA),
        style: [
            {
                selector: 'node',
                style: {
                    'background-color': ele => ele.data('color') || NODE_DEFAULT_COLOR,
                    'shape': ele => cyShapeFor(ele.data('shape')),
                    'label': 'data(name)',
                    'color': '#fff',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'font-size': '11px',
                    // Rectangular presets get a wider box; everything else stays 60×60.
                    'width': ele => (ele.data('shape') === 'start' || ele.data('shape') === 'end') ? 85 : 60,
                    'height': ele => (ele.data('shape') === 'start' || ele.data('shape') === 'end') ? 45 : 60,
                    'text-wrap': 'wrap',
                    'text-max-width': '55px'
                }
            },
            {
                selector: 'node:selected',
                style: { 'border-width': 3, 'border-color': '#b45309' }
            },
            {
                // Fixed presentation for sub-flow reference nodes. It comes after
                // the generic 'node' rule so it overrides shape/colour/size,
                // making these nodes visually distinct and non-styleable.
                selector: 'node[node_type = "SUBFLOW"]',
                style: {
                    'shape': 'round-rectangle',
                    'background-color': SUBFLOW_COLOR,
                    'border-width': 2,
                    'border-color': '#4c1d95',
                    'border-style': 'double',
                    'width': 95,
                    'height': 50
                }
            },
            {
                selector: 'edge',
                style: {
                    'width': ele => ele.data('width') || 2,
                    'line-color': ele => ele.data('color') || EDGE_DEFAULT_COLOR,
                    'target-arrow-color': ele => ele.data('color') || EDGE_DEFAULT_COLOR,
                    'source-arrow-color': ele => ele.data('color') || EDGE_DEFAULT_COLOR,
                    'target-arrow-shape': 'triangle',
                    'source-arrow-shape': 'none',
                    'curve-style': 'bezier',
                    'label': 'data(label)',
                    'font-size': '10px',
                    'color': '#475569'
                }
            },
            { selector: 'edge[direction="backward"]', style: { 'target-arrow-shape': 'none', 'source-arrow-shape': 'triangle' } },
            { selector: 'edge[direction="both"]',     style: { 'target-arrow-shape': 'triangle', 'source-arrow-shape': 'triangle' } },
            { selector: 'edge[direction="none"]',      style: { 'target-arrow-shape': 'none', 'source-arrow-shape': 'none' } },
            {
                selector: 'edge:selected',
                style: { 'line-color': '#f59e0b', 'target-arrow-color': '#f59e0b', 'source-arrow-color': '#f59e0b' }
            }
        ],
        // `fit: false` prevents Cytoscape from auto-zooming the initial layout.
        // A bare 'fit' would blow a single (small) node up to fill the whole
        // viewport; we always apply the zoom-capped `smartFit` on ready instead.
        layout: { name: INITIAL_LAYOUT, animate: false, fit: false }
    });

    // Keep the counter ahead of any existing numeric node id.
    cy.nodes().forEach(n => {
        const num = parseInt(n.id().replace(/\D/g, ''), 10);
        if (!isNaN(num) && num >= nodeCounter) nodeCounter = num + 1;
    });

    /* ===================== AUTOMATIC LAYOUT ===================== */
    // Cap the zoom applied by "fit to screen". `cy.fit()` scales the graph until
    // it fills the viewport, which makes a handful of nodes look enormous. We fit
    // first, then, if the resulting zoom went past this ceiling, clamp it back and
    // re-center so small graphs keep a natural, readable node size.
    // Tune this value to taste: 1.0 = real size (no magnification); lower values
    // (e.g. 0.75) keep nodes smaller, higher values allow more zoom-in.
    const MAX_FIT_ZOOM = 1.4;

    // Fit the whole graph into the viewport without over-zooming small graphs.
    function smartFit(padding) {
        const pad = typeof padding === 'number' ? padding : 30;
        cy.fit(cy.elements(), pad);
        if (cy.zoom() > MAX_FIT_ZOOM) {
            cy.zoom(MAX_FIT_ZOOM);
            cy.center(cy.elements());
        }
    }

    // Pick the nodes that should sit at the top (or left) of the hierarchy. We
    // prefer the semantic "start" shape; if the user has not tagged any node we
    // fall back to the graph sources (nodes with no incoming edge).
    function getRootNodes() {
        let roots = cy.nodes().filter(n => n.data('shape') === 'start');
        if (roots.length === 0) roots = cy.nodes().filter(n => n.indegree(false) === 0);
        return roots;
    }

    // Auto-orient the whole graph with a directed breadth-first (hierarchical)
    // layout. `orientation` is 'td' (top-down, the standard default) or 'lr'
    // (left-right). Start nodes end up on top/left and end nodes at the
    // bottom/right, following the edge direction.
    function runAutoLayout(orientation) {
        const roots = getRootNodes();
        const options = {
            name: 'breadthfirst',
            directed: true,
            padding: 30,
            spacingFactor: 1.3,
            // Do not let the layout fit on its own: it would over-zoom small
            // graphs. We fit ourselves via `smartFit` once the layout settles.
            fit: false,
            animate: true,
            animationDuration: 350
        };
        if (roots.length) options.roots = roots;
        // 'breadthfirst' lays out top-down by default; swap x/y to get left-right.
        if (orientation === 'lr') {
            options.transform = (node, pos) => ({ x: pos.y, y: pos.x });
        }
        const layout = cy.layout(options);
        // Apply the zoom-capped fit only after the animated layout has finished.
        layout.one('layoutstop', () => smartFit(30));
        layout.run();
    }

    // Brand-new graphs (no stored coordinates) get the standard top-down layout.
    // Graphs that already carry positions keep them, but we still apply the
    // zoom-capped `smartFit` so a single/small node is never blown up to fill
    // the whole viewport.
    if (!HAS_SAVED_POSITIONS && cy.nodes().length) {
        runAutoLayout('td');
    } else if (cy.nodes().length) {
        smartFit(30);
    }

    // Toolbar buttons: re-run the automatic layout on demand.
    document.getElementById('btn-layout-td').addEventListener('click', () => runAutoLayout('td'));
    document.getElementById('btn-layout-lr').addEventListener('click', () => runAutoLayout('lr'));
    // Fit the whole graph into the visible viewport (resize to screen).
    document.getElementById('btn-fit').addEventListener('click', () => smartFit(30));

    function setStatus(msg, isError) {
        const s = document.getElementById('status');
        s.textContent = msg;
        s.style.color = isError ? '#b91c1c' : '#166534';
    }

    /* ===================== SIDEBAR / INSPECTOR ===================== */
    const sidebar = document.getElementById('map-sidebar');
    const editorBody = document.getElementById('editor-body');
    const sidebarEmpty = document.getElementById('sidebar-empty');
    const nodeProps = document.getElementById('node-props');
    const edgeProps = document.getElementById('edge-props');
    // Read-only field that displays the selected node's unique Cytoscape id.
    const nodeIdInput = document.getElementById('node-id');
    // Read-only field showing the node's compact, globally unique id (node_uid).
    const nodeUidInput = document.getElementById('node-uid');
    // Button that copies the node_uid to the clipboard.
    const copyUidButton = document.getElementById('btn-copy-uid');
    const nodeNameInput = document.getElementById('node-name');
    const nodeDescriptionInput = document.getElementById('node-description');
    const edgeLabelInput = document.getElementById('edge-label');
    const edgeWidthInput = document.getElementById('edge-width');
    const edgeWidthVal = document.getElementById('edge-width-val');
    const edgeDirGroup = document.getElementById('edge-dir');
    const nodeShapeGroup = document.getElementById('node-shape');
    // Node-type controls (pure vs. sub-flow reference).
    const nodeTypeGroup = document.getElementById('node-type');
    const nodeSubflowField = document.getElementById('node-subflow-field');
    const nodeSubflowSelect = document.getElementById('node-subflow');
    const nodeStyleFields = document.getElementById('node-style-fields');
    const nodeSubflowOpen = document.getElementById('node-subflow-open');
    // "User Story" tab button, hidden while a sub-flow node is selected.
    const storiesTabButton = document.getElementById('tab-btn-stories');

    let selectedEl = null;

    function normHex(c) { return (c || '').toLowerCase(); }

    // Build the swatch grids.
    function buildSwatchGrid(grid) {
        const target = grid.dataset.target;
        grid.innerHTML = '';
        SWATCH_PALETTE.forEach(color => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'swatch';
            btn.style.backgroundColor = color;
            btn.title = color;
            btn.dataset.color = color;
            btn.addEventListener('click', () => applyColor(target, color));
            grid.appendChild(btn);
        });
    }

    function highlightSwatch(target, color) {
        const grid = document.querySelector(`.swatch-grid[data-target="${target}"]`);
        if (!grid) return;
        grid.querySelectorAll('.swatch').forEach(s => {
            s.classList.toggle('active', normHex(s.dataset.color) === normHex(color));
        });
    }

    function applyColor(target, color) {
        if (!selectedEl) return;
        if (target === 'node-color' && selectedEl.isNode()) selectedEl.data('color', color);
        else if (target === 'edge-color' && selectedEl.isEdge()) selectedEl.data('color', color);
        highlightSwatch(target, color);
    }

    document.querySelectorAll('.swatch-grid').forEach(buildSwatchGrid);

    // Highlight the active shape button that matches the node's current shape.
    function highlightShape(shapeKey) {
        nodeShapeGroup.querySelectorAll('button').forEach(b => {
            b.classList.toggle('active', b.dataset.shape === shapeKey);
        });
    }

    // Apply a shape preset to the selected node (sets the shape and, for semantic
    // presets, the matching colour) and refresh the inspector highlighting.
    function applyShape(shapeKey) {
        if (!selectedEl || !selectedEl.isNode()) return;
        selectedEl.data('shape', shapeKey);
        const preset = SHAPE_PRESETS[shapeKey];
        if (preset && preset.color) {
            selectedEl.data('color', preset.color);
            highlightSwatch('node-color', preset.color);
        }
        highlightShape(shapeKey);
    }

    nodeShapeGroup.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => applyShape(btn.dataset.shape));
    });

    /* ===================== NODE TYPE (pure vs. sub-flow) ===================== */
    // Populate the sub-flow dropdown once with the maps offered by the backend.
    function buildSubflowOptions() {
        nodeSubflowSelect.innerHTML = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = '— Seleziona un flusso —';
        nodeSubflowSelect.appendChild(placeholder);
        SUBFLOWS.forEach(sf => {
            const opt = document.createElement('option');
            opt.value = String(sf.id);
            opt.textContent = sf.name;
            nodeSubflowSelect.appendChild(opt);
        });
    }
    buildSubflowOptions();

    // Show or hide the "User Story" tab button. Sub-flow nodes have no stories,
    // so the whole tab is hidden; if it was active we fall back to "Proprietà".
    function setStoriesTabVisible(visible) {
        if (!storiesTabButton) return;
        storiesTabButton.style.display = visible ? '' : 'none';
        if (!visible && activeTab === 'stories') activateTab('props');
    }

    // Point the "open sub-flow" link at the referenced map and toggle it.
    function updateSubflowLink(subFlowId) {
        if (!nodeSubflowOpen) return;
        if (subFlowId && MAP_EDITOR_URL) {
            nodeSubflowOpen.href = MAP_EDITOR_URL.replace(/\/0\/?$/, '/' + subFlowId + '/');
            nodeSubflowOpen.style.display = 'inline-block';
        } else {
            nodeSubflowOpen.style.display = 'none';
        }
    }

    // Reflect the node type in the inspector: toggle the buttons and show/hide
    // the sub-flow dropdown and the (pure-only) shape/colour fields.
    function reflectNodeType(nodeType) {
        const isSub = nodeType === 'SUBFLOW';
        nodeTypeGroup.querySelectorAll('button').forEach(b => {
            b.classList.toggle('active', b.dataset.type === (isSub ? 'SUBFLOW' : 'PURE'));
        });
        nodeSubflowField.style.display = isSub ? 'block' : 'none';
        nodeStyleFields.style.display = isSub ? 'none' : 'block';
        // Sub-flow nodes own no User Stories: hide the tab entirely.
        setStoriesTabVisible(!isSub);
        if (!isSub) updateSubflowLink(null);
    }

    // Switch the selected node between PURE and SUBFLOW. A SUBFLOW node loses its
    // custom shape/colour (a fixed style takes over) and gains a sub_flow ref.
    function applyNodeType(nodeType) {
        if (!selectedEl || !selectedEl.isNode()) return;
        if (nodeType === 'SUBFLOW') {
            selectedEl.data('node_type', 'SUBFLOW');
            selectedEl.removeData('shape');
            selectedEl.removeData('color');
            const current = selectedEl.data('sub_flow');
            nodeSubflowSelect.value = current ? String(current) : '';
            reflectNodeType('SUBFLOW');
            updateSubflowLink(current || null);
        } else {
            selectedEl.data('node_type', 'PURE');
            selectedEl.removeData('sub_flow');
            reflectNodeType('PURE');
        }
    }
    nodeTypeGroup.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => applyNodeType(btn.dataset.type));
    });
    nodeSubflowSelect.addEventListener('change', () => {
        if (!selectedEl || !selectedEl.isNode()) return;
        const val = nodeSubflowSelect.value;
        if (val) selectedEl.data('sub_flow', val);
        else selectedEl.removeData('sub_flow');
        updateSubflowLink(val || null);
    });

    // Copy the currently displayed node_uid to the clipboard. Falls back to a
    // legacy execCommand copy when the async Clipboard API is unavailable
    // (e.g. non-secure contexts).
    if (copyUidButton) {
        copyUidButton.addEventListener('click', async () => {
            const value = (nodeUidInput && nodeUidInput.value) || '';
            // Ignore the placeholder shown for not-yet-saved nodes.
            if (!value || value.startsWith('(')) {
                setStatus('No UUID to copy yet (save the node first).', true);
                return;
            }
            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(value);
                } else {
                    nodeUidInput.select();
                    document.execCommand('copy');
                    nodeUidInput.setSelectionRange(0, 0);
                    nodeUidInput.blur();
                }
                setStatus('Node UUID copied ✔', false);
            } catch (err) {
                setStatus('Could not copy the UUID: ' + err, true);
            }
        });
    }

    function showInspectorFor(el) {
        selectedEl = el;
        if (!el) {
            sidebarEmpty.style.display = 'block';
            nodeProps.style.display = 'none';
            edgeProps.style.display = 'none';
            setStoriesTabVisible(true);
            return;
        }
        sidebarEmpty.style.display = 'none';
        if (el.isNode()) {
            nodeProps.style.display = 'block';
            edgeProps.style.display = 'none';
            // Show the unique node id (read-only) so the user can identify the node.
            if (nodeIdInput) nodeIdInput.value = el.id();
            // Show the compact global node_uid (read-only). It only exists for
            // nodes already persisted server-side; new unsaved nodes show a hint.
            if (nodeUidInput) {
                const uids = CONFIG.nodeUids || {};
                nodeUidInput.value = uids[el.id()] || '(saved after next save)';
            }
            nodeNameInput.value = el.data('name') || '';
            nodeDescriptionInput.value = el.data('description') || '';
            highlightSwatch('node-color', el.data('color') || NODE_DEFAULT_COLOR);
            highlightShape(el.data('shape') || '');
            // Reflect the node nature and the referenced sub-flow (if any).
            const nodeType = el.data('node_type') || 'PURE';
            reflectNodeType(nodeType);
            const subFlowId = el.data('sub_flow') || '';
            nodeSubflowSelect.value = subFlowId ? String(subFlowId) : '';
            if (nodeType === 'SUBFLOW') updateSubflowLink(subFlowId || null);
        } else {
            nodeProps.style.display = 'none';
            edgeProps.style.display = 'block';
            setStoriesTabVisible(true);
            edgeLabelInput.value = el.data('label') || '';
            const w = el.data('width') || 2;
            edgeWidthInput.value = w;
            edgeWidthVal.textContent = `${w} px`;
            const dir = el.data('direction') || 'forward';
            edgeDirGroup.querySelectorAll('button').forEach(b => {
                b.classList.toggle('active', b.dataset.dir === dir);
            });
            highlightSwatch('edge-color', el.data('color') || EDGE_DEFAULT_COLOR);
        }
    }

    // Sync the inspector with the Cytoscape selection.
    function syncInspector() {
        const sel = cy.$(':selected');
        showInspectorFor(sel.length === 1 ? sel[0] : null);
        // Keep the User Story tab aligned with the current node selection.
        refreshStoriesTab();
    }
    cy.on('select', 'node, edge', syncInspector);
    cy.on('unselect', 'node, edge', syncInspector);

    // Inspector input handlers.
    nodeNameInput.addEventListener('input', () => {
        if (selectedEl && selectedEl.isNode()) selectedEl.data('name', nodeNameInput.value);
    });
    nodeDescriptionInput.addEventListener('input', () => {
        if (selectedEl && selectedEl.isNode()) selectedEl.data('description', nodeDescriptionInput.value);
    });
    edgeLabelInput.addEventListener('input', () => {
        if (selectedEl && selectedEl.isEdge()) selectedEl.data('label', edgeLabelInput.value);
    });
    edgeWidthInput.addEventListener('input', () => {
        const w = parseInt(edgeWidthInput.value, 10);
        edgeWidthVal.textContent = `${w} px`;
        if (selectedEl && selectedEl.isEdge()) selectedEl.data('width', w);
    });
    edgeDirGroup.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
            if (!selectedEl || !selectedEl.isEdge()) return;
            selectedEl.data('direction', btn.dataset.dir);
            edgeDirGroup.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });

    // Toggle / collapse sidebar.
    function setSidebarOpen(open) {
        sidebar.classList.toggle('collapsed', !open);
        editorBody.classList.toggle('sidebar-hidden', !open);
        setTimeout(() => cy.resize(), 260);
    }
    document.getElementById('btn-toggle-sidebar').addEventListener('click', () => {
        setSidebarOpen(sidebar.classList.contains('collapsed'));
    });
    document.getElementById('sidebar-reopen').addEventListener('click', () => setSidebarOpen(true));

    /* ===================== RICH-TEXT DESCRIPTION (Quill) ===================== */
    // Initialise Quill immediately so the editor is fully wired before the modal opens,
    // then keep `mapDescription` in sync so the Save handler can ship it.
    let descriptionEditor = null;
    const descriptionModal = document.getElementById('description-modal');

    function initDescriptionEditor() {
        if (descriptionEditor) return;
        if (typeof Quill === 'undefined') {
            console.error('Quill failed to load: the description editor is unavailable.');
            return;
        }
        descriptionEditor = new Quill('#description-editor', {
            theme: 'snow',
            placeholder: 'Describe this application flow…',
            modules: {
                toolbar: [
                    [{ header: [1, 2, 3, false] }],
                    ['bold', 'italic', 'underline', 'strike'],
                    [{ list: 'ordered' }, { list: 'bullet' }],
                    ['blockquote', 'code-block', 'link'],
                    ['clean']
                ]
            }
        });
        if (mapDescription) {
            descriptionEditor.clipboard.dangerouslyPasteHTML(mapDescription);
        }
        descriptionEditor.on('text-change', () => {
            mapDescription = descriptionEditor.getSemanticHTML();
        });
    }

    // Build the editor up-front (the modal is only display:none, Quill handles that fine).
    initDescriptionEditor();

    if (descriptionModal) {
        // Recalculate layout and drop the cursor into the editor once the modal is visible.
        descriptionModal.addEventListener('shown.bs.modal', () => {
            if (descriptionEditor) descriptionEditor.focus();
        });
    }


    /* ===================== TAB: Proprietà / User Story (HTMX) ===================== */
    const tabButtons = document.querySelectorAll('.sidebar-tabs button');
    const tabPanels = {
        props: document.getElementById('tab-props'),
        stories: document.getElementById('tab-stories'),
    };
    const storiesContent = document.getElementById('stories-content');
    let activeTab = 'props';

    function activateTab(name) {
        activeTab = name;
        tabButtons.forEach(b => b.classList.toggle('active', b.dataset.tab === name));
        Object.entries(tabPanels).forEach(([key, panel]) => {
            panel.classList.toggle('active', key === name);
        });
        if (name === 'stories') refreshStoriesTab();
    }
    tabButtons.forEach(btn => btn.addEventListener('click', () => activateTab(btn.dataset.tab)));

    // Load the User Stories of the selected node into #stories-content via HTMX.
    function refreshStoriesTab() {
        if (activeTab !== 'stories') return;

        const sel = cy.$(':selected');
        const node = (sel.length === 1 && sel[0].isNode()) ? sel[0] : null;

        if (!node) {
            storiesContent.innerHTML =
                '<div class="sidebar-empty">Seleziona un nodo per vederne le User Story.</div>';
            return;
        }
        const url = USER_STORIES_URL.replace('__NODE_ID__', encodeURIComponent(node.id()));
        htmx.ajax('GET', url, { target: '#stories-content', swap: 'innerHTML' });
    }

    // --- Add node ---
    document.getElementById('btn-add-node').addEventListener('click', () => {
        const name = prompt('Node name:', 'New node');
        if (name === null) return;
        const id = 'n' + (nodeCounter++);
        const pan = cy.pan(), zoom = cy.zoom();
        cy.add({
            group: 'nodes',
            data: { id: id, name: name, description: '', color: NODE_DEFAULT_COLOR },
            position: {
                x: (cy.width() / 2 - pan.x) / zoom,
                y: (cy.height() / 2 - pan.y) / zoom
            }
        });
    });

    // --- Add edge between two selected nodes ---
    document.getElementById('btn-add-edge').addEventListener('click', () => {
        const selected = cy.nodes(':selected');
        if (selected.length !== 2) {
            setStatus('Select exactly 2 nodes to link.', true);
            return;
        }
        const label = prompt('Edge label (optional):', '') || '';
        cy.add({
            group: 'edges',
            data: {
                id: 'e' + Date.now(),
                source: selected[0].id(),
                target: selected[1].id(),
                label: label,
                color: EDGE_DEFAULT_COLOR,
                width: 2,
                direction: 'forward'
            }
        });
        setStatus('Edge created.', false);
    });

    // --- Rename selected node/edge ---
    document.getElementById('btn-rename').addEventListener('click', () => {
        const sel = cy.$(':selected');
        if (sel.length !== 1) {
            setStatus('Select exactly 1 element to rename.', true);
            return;
        }
        const el = sel[0];
        const key = el.isNode() ? 'name' : 'label';
        const current = el.data(key) || '';
        const value = prompt('New label:', current);
        if (value === null) return;
        el.data(key, value);
        showInspectorFor(el);
    });

    // --- Delete selected ---
    document.getElementById('btn-delete').addEventListener('click', () => {
        const sel = cy.$(':selected');
        if (sel.length === 0) {
            setStatus('Nothing selected.', true);
            return;
        }
        sel.remove();
        showInspectorFor(null);
    });

    // --- Save to backend ---
    document.getElementById('btn-save').addEventListener('click', async () => {
        setStatus('Saving…', false);
        const json = cy.json();
        const payload = {
            name: document.getElementById('map-name').value,
            description: mapDescription,
            elements: json.elements
        };
        try {
            const resp = await fetch(SAVE_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify(payload)
            });
            const result = await resp.json();
            if (result.ok) {
                setStatus('Saved ✔', false);
            } else {
                setStatus('Error: ' + result.error, true);
            }
        } catch (err) {
            setStatus('Network error: ' + err, true);
        }
    });
})();

