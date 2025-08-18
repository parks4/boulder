// Graph resize functionality
(function() {
    'use strict';

    let isResizing = false;
    let startY = 0;
    let startHeight = 0;
    let graphContainer = null;
    let reactorGraph = null;

    function initializeResize() {
        // Wait for the graph container to be available
        const checkContainer = setInterval(() => {
            graphContainer = document.getElementById('graph-container');
            reactorGraph = document.getElementById('reactor-graph');

            if (graphContainer && reactorGraph) {
                clearInterval(checkContainer);
                setupResizeHandle();
            }
        }, 100);
    }

    function setupResizeHandle() {
        // Create resize handle
        const resizeHandle = document.createElement('div');
        resizeHandle.id = 'resize-handle';
        resizeHandle.style.cssText = `
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 6px;
            background: linear-gradient(90deg, transparent 0%, var(--border-color, #ccc) 20%, var(--border-color, #ccc) 80%, transparent 100%);
            cursor: ns-resize;
            opacity: 0;
            transition: opacity 0.2s ease;
            z-index: 10;
        `;

        graphContainer.appendChild(resizeHandle);

        // Show handle on hover
        graphContainer.addEventListener('mouseenter', () => {
            resizeHandle.style.opacity = '1';
        });

        graphContainer.addEventListener('mouseleave', () => {
            if (!isResizing) {
                resizeHandle.style.opacity = '0';
            }
        });

        // Handle mouse events
        resizeHandle.addEventListener('mousedown', startResize);
        document.addEventListener('mousemove', resize);
        document.addEventListener('mouseup', stopResize);

        // Prevent text selection during resize
        resizeHandle.addEventListener('selectstart', (e) => e.preventDefault());
        resizeHandle.addEventListener('dragstart', (e) => e.preventDefault());
    }

    function startResize(e) {
        isResizing = true;
        startY = e.clientY;
        startHeight = parseInt(getComputedStyle(reactorGraph).height, 10);

        // Add visual feedback
        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';
        graphContainer.classList.add('resizing');

        e.preventDefault();
    }

    function resize(e) {
        if (!isResizing) return;

        const deltaY = e.clientY - startY;
        const newHeight = Math.max(200, startHeight + deltaY); // Minimum 200px

        reactorGraph.style.height = newHeight + 'px';

        e.preventDefault();
    }

    function stopResize() {
        if (!isResizing) return;

        isResizing = false;

        // Remove visual feedback
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        graphContainer.classList.remove('resizing');

        // Hide resize handle if mouse is not over container
        const resizeHandle = document.getElementById('resize-handle');
        if (resizeHandle && !graphContainer.matches(':hover')) {
            resizeHandle.style.opacity = '0';
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeResize);
    } else {
        initializeResize();
    }

    // Re-initialize when Dash updates the DOM (for dynamic content)
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'childList') {
                const graphContainer = document.getElementById('graph-container');
                const resizeHandle = document.getElementById('resize-handle');

                if (graphContainer && !resizeHandle) {
                    // Container exists but no resize handle, set it up
                    setTimeout(setupResizeHandle, 100);
                }
            }
        });
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

})();
