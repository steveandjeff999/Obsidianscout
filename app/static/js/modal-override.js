/**
 * Modal Override for 5454 Scout 2026
 * This file completely replaces Bootstrap's modal functionality with a custom implementation
 * that prevents any flashing or movement issues.
 */

// Wait for DOM to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
    // Find all delete buttons that trigger modals
    const deleteButtons = document.querySelectorAll('[data-bs-toggle="modal"]');
    
    // Replace Bootstrap's modal functionality with our own
    deleteButtons.forEach(function(button) {
        // Get the target modal ID
        const modalId = button.getAttribute('data-bs-target');
        if (!modalId) return;
        
        // Remove the modal from wherever it is in the DOM
        const modal = document.querySelector(modalId);
        if (!modal) return;
        
        // Remove Bootstrap's data attributes to prevent their modal code from running
        button.removeAttribute('data-bs-toggle');
        button.removeAttribute('data-bs-target');
        
        // Clone the modal content
        const modalContent = modal.querySelector('.modal-content').cloneNode(true);
        
        // Create our own click handler
        button.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Create our own modal overlay
            createCustomModal(modalId, modalContent);
        });
        
        // Hide the original modal
        modal.style.display = 'none';
    });
});

/**
 * Create a completely custom modal
 */
function createCustomModal(id, content) {
    // Remove any existing custom modals
    const existingModals = document.querySelectorAll('.custom-modal-container');
    existingModals.forEach(modal => modal.remove());
    
    // Create container
    const modalContainer = document.createElement('div');
    modalContainer.className = 'custom-modal-container';
    modalContainer.id = id.replace('#', '') + '-custom';
    modalContainer.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
    `;
    
    // Create the modal dialog
    const modalDialog = document.createElement('div');
    modalDialog.className = 'custom-modal-dialog';
    modalDialog.style.cssText = `
        background: white;
        border-radius: 5px;
        max-width: 500px;
        width: 100%;
        box-shadow: 0 5px 15px rgba(0,0,0,.5);
        position: relative;
        animation: none;
        transition: none;
    `;
    
    // Append content to dialog
    modalDialog.appendChild(content);
    modalContainer.appendChild(modalDialog);
    
    // Add to DOM
    document.body.appendChild(modalContainer);
    
    // Disable body scrolling
    document.body.style.overflow = 'hidden';
    
    // Find all close buttons and wire them up
    const closeButtons = modalContainer.querySelectorAll('[data-bs-dismiss="modal"], .btn-close, .btn-secondary');
    closeButtons.forEach(button => {
        button.addEventListener('click', function() {
            closeCustomModal(modalContainer);
        });
    });
    
    // Also close on background click
    modalContainer.addEventListener('click', function(e) {
        if (e.target === modalContainer) {
            closeCustomModal(modalContainer);
        }
    });
}

/**
 * Close the custom modal
 */
function closeCustomModal(modalContainer) {
    // Remove the modal
    modalContainer.remove();
    
    // Re-enable scrolling
    document.body.style.overflow = '';
}