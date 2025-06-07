/**
 * Custom JS to handle Shift key for cursor changes and edge creation in Cytoscape.
 * This is loaded automatically by Dash from the assets/ folder.
 */
document.addEventListener('DOMContentLoaded', function() {
    console.log('Shift cursor JS loaded');
    const cyContainer = document.querySelector('#reactor-graph > div');
    let sourceNode = null;
    let previewEdge = null;
    
    // Function to trigger toast notifications
    function showToast(message, type = 'info') {
        console.log('Attempting to show toast:', { message, type });
        // Update the Store to trigger the callback
        const store = document.getElementById('toast-trigger');
        if (store) {
            store.setAttribute('data-value', JSON.stringify({ message, type }));
            // Trigger a change event
            store.dispatchEvent(new Event('change'));
        }
    }
    
    // Listen for Shift key
    document.addEventListener('keydown', function(e) {
        console.log('Keydown event:', e.key);
        if (e.key === 'Shift' && cyContainer) {
            console.log('Shift pressed, showing initial toast');
            cyContainer.style.cursor = 'crosshair';
            showToast('Hold Shift and click on first node to start connection');
        }
    });
    
    document.addEventListener('keyup', function(e) {
        console.log('Keyup event:', e.key);
        if (e.key === 'Shift' && cyContainer) {
            console.log('Shift released, showing cancel toast');
            cyContainer.style.cursor = 'default';
            // Remove preview edge when Shift is released
            if (previewEdge) {
                previewEdge.remove();
                previewEdge = null;
            }
            sourceNode = null;
            showToast('Connection cancelled');
        }
    });

    // Listen for node clicks and mouse movement
    if (window.cy) {
        console.log('Cytoscape instance found, setting up event listeners');
        // Handle node clicks
        window.cy.on('tap', 'node', function(evt) {
            console.log('Node tap event:', evt.target.id());
            const node = evt.target;
            
            // If Shift is pressed, this is the source node
            if (evt.originalEvent.shiftKey) {
                sourceNode = node;
                console.log('Source node selected:', node.id());
                showToast('Now click on second node to complete connection', 'info');
            }
            // If we have a source node and Shift is still pressed, create an edge
            else if (sourceNode && evt.originalEvent.shiftKey) {
                const targetNode = node;
                if (sourceNode.id() !== targetNode.id()) {  // Don't create self-loops
                    console.log('Creating edge from', sourceNode.id(), 'to', targetNode.id());
                    // Trigger a custom event that Dash can listen to
                    window.dispatchEvent(new CustomEvent('create-edge', {
                        detail: {
                            source: sourceNode.id(),
                            target: targetNode.id()
                        }
                    }));
                    showToast('Connection created successfully!', 'success');
                } else {
                    showToast('Cannot connect a node to itself', 'error');
                }
                // Remove preview edge after creating the real edge
                if (previewEdge) {
                    previewEdge.remove();
                    previewEdge = null;
                }
                sourceNode = null;
            }
        });

        // Handle mouse movement to update preview edge
        window.cy.on('mouseover', 'node', function(evt) {
            if (sourceNode && evt.originalEvent.shiftKey) {
                const targetNode = evt.target;
                if (sourceNode.id() !== targetNode.id()) {  // Don't show preview for self-loops
                    // Remove existing preview if any
                    if (previewEdge) {
                        previewEdge.remove();
                    }
                    // Create new preview edge
                    previewEdge = window.cy.add({
                        group: 'edges',
                        data: {
                            source: sourceNode.id(),
                            target: targetNode.id(),
                            preview: true
                        },
                        style: {
                            'line-color': '#999',
                            'line-style': 'dashed',
                            'line-dash-pattern': [5, 5],
                            'target-arrow-shape': 'triangle',
                            'target-arrow-color': '#999',
                            'opacity': 0.7
                        }
                    });
                }
            }
        });

        // Remove preview when mouse leaves a node
        window.cy.on('mouseout', 'node', function(evt) {
            if (previewEdge) {
                previewEdge.remove();
                previewEdge = null;
            }
        });
    } else {
        console.log('Cytoscape instance not found!');
    }
}); 