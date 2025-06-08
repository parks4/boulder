// Make Dash Bootstrap Modal draggable by its header
window.addEventListener('DOMContentLoaded', function() {
    function enableDraggableModal() {
        // Find the open modal dialog
        const modal = document.querySelector('.modal.show');
        if (!modal) return;
        const dialog = modal.querySelector('.modal-dialog');
        const header = modal.querySelector('.modal-header');
        if (!dialog || !header) return;

        let isDragging = false, startX, startY, startLeft, startTop;

        header.style.cursor = 'move';

        header.onmousedown = function(e) {
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            const rect = dialog.getBoundingClientRect();
            startLeft = rect.left;
            startTop = rect.top;
            dialog.style.position = 'fixed';
            dialog.style.margin = 0;
            dialog.style.left = startLeft + 'px';
            dialog.style.top = startTop + 'px';
            document.body.style.userSelect = 'none';
        };

        document.onmousemove = function(e) {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            dialog.style.left = (startLeft + dx) + 'px';
            dialog.style.top = (startTop + dy) + 'px';
        };

        document.onmouseup = function() {
            isDragging = false;
            document.body.style.userSelect = '';
        };
    }

    // Listen for modal open events (since Dash re-renders modals)
    const observer = new MutationObserver(() => {
        if (document.querySelector('.modal.show')) {
            enableDraggableModal();
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Also try to enable on initial load
    enableDraggableModal();
}); 