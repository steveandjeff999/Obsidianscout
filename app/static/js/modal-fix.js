/**
 * FRC Scouting Platform
 * Modal positioning fix - Complete solution for teleporting modals
 */

document.addEventListener('DOMContentLoaded', function() {
    // Override Bootstrap's modal handling entirely
    // This is an aggressive fix that takes complete control of modal positioning
    
    // 1. Patch Bootstrap modal functionality before it initializes
    const originalModalShow = bootstrap.Modal.prototype.show;
    const originalModalHide = bootstrap.Modal.prototype.hide;
    
    bootstrap.Modal.prototype.show = function() {
        // Apply our fixes before showing modal
        const modalElement = this._element;
        const modalDialog = modalElement.querySelector('.modal-dialog');
        
        // Force fixed positioning styles
        modalElement.style.position = 'fixed';
        modalElement.style.display = 'block';
        modalElement.style.paddingRight = '0';
        modalElement.style.top = '0';
        modalElement.style.left = '0';
        modalElement.style.width = '100%';
        modalElement.style.height = '100%';
        modalElement.style.overflow = 'hidden';
        modalElement.style.outline = '0';
        
        // Fix dialog position
        modalDialog.style.position = 'absolute';
        modalDialog.style.top = '50%';
        modalDialog.style.left = '50%';
        modalDialog.style.transform = 'translate(-50%, -50%)';
        modalDialog.style.margin = '0';
        modalDialog.style.maxWidth = '500px';
        modalDialog.style.width = '100%';
        modalDialog.style.pointerEvents = 'auto';
        
        // Prevent body scrolling and shifting
        document.body.style.overflow = 'hidden';
        document.body.style.paddingRight = '0';
        
        // Call the original Bootstrap method
        originalModalShow.apply(this);
        
        // Create a static backdrop if it doesn't exist
        fixBackdrop();
        
        // Add specific mouse event handlers to the modal to prevent hover movement
        addMouseEventHandlers(modalElement);
    };
    
    bootstrap.Modal.prototype.hide = function() {
        // Call the original Bootstrap method
        originalModalHide.apply(this);
        
        // Reset body styles
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';
    };
    
    // Handle mouse events to prevent modal movement on hover
    function addMouseEventHandlers(modal) {
        // Apply a hard fixed position once when handlers are attached
        fixAllPositions(modal);

        // Throttle repeated reflows: avoid reapplying styles on every mousemove.
        // Only reapply positioning at most once per 100ms when user interacts.
        let lastApplied = 0;
        function throttledFix() {
            const now = Date.now();
            if (now - lastApplied < 100) return;
            lastApplied = now;
            // Use rAF for layout stability
            window.requestAnimationFrame(() => fixAllPositions(modal));
        }

        // Use pointer events (covers mouse and touch) and focus/blur instead of mousemove
        modal.addEventListener('pointerenter', function(e) {
            if (e.target.closest('.modal, .modal-dialog, .modal-content')) throttledFix();
        }, true);

        modal.addEventListener('pointerdown', function(e) {
            if (e.target.closest('.modal, .modal-dialog, .modal-content')) throttledFix();
        }, true);

        // Also respond to focus changes inside the modal (some browsers modify outline/borders)
        modal.addEventListener('focusin', function() { throttledFix(); }, true);
    }
    
    // Helper to fix all positions at once
    function fixAllPositions(modal) {
        // Fix the main modal container
        modal.style.position = 'fixed';
        modal.style.top = '0';
        modal.style.left = '0';
        modal.style.width = '100%';
        modal.style.height = '100%';
        
        // Fix the dialog position
        const dialog = modal.querySelector('.modal-dialog');
        if (dialog) {
            dialog.style.position = 'absolute';
            dialog.style.top = '50%';
            dialog.style.left = '50%';
            dialog.style.transform = 'translate(-50%, -50%)';
            dialog.style.margin = '0';
            
            // Apply the same hover protection to dialog
            dialog.style.pointerEvents = 'auto';
            dialog.style.transition = 'none !important';
        }
        
        // Fix content, header, body, footer
        const modalContent = modal.querySelector('.modal-content');
        if (modalContent) {
            modalContent.style.transition = 'none !important';
            modalContent.style.transform = 'none';
            
            // Make sure the content responds to hover but doesn't move
            const contentParts = modalContent.querySelectorAll('.modal-header, .modal-body, .modal-footer');
            contentParts.forEach(part => {
                part.style.transition = 'none !important';
                part.style.transform = 'none';
            });
        }
    }
    
    // 2. Direct event handlers for all existing and future modals
    function setupModalHandlers() {
        const modals = document.querySelectorAll('.modal');
        
        modals.forEach(function(modal) {
            // Skip if we've already processed this modal
            if (modal.dataset.fixApplied === 'true') return;
            
            // Direct CSS fixes for the modal
            modal.style.position = 'fixed';
            modal.style.top = '0';
            modal.style.left = '0';
            modal.style.width = '100%';
            modal.style.height = '100%';
            modal.style.zIndex = '1050';
            modal.style.overflow = 'hidden';
            modal.style.outline = '0';
            
            // Set an !important style to prevent anything from changing the position
            addImportantStyles(modal, {
                'position': 'fixed',
                'top': '0',
                'left': '0'
            });
            
            // Fix dialog position
            const dialog = modal.querySelector('.modal-dialog');
            if (dialog) {
                dialog.style.position = 'absolute';
                dialog.style.top = '50%';
                dialog.style.left = '50%';
                dialog.style.transform = 'translate(-50%, -50%)';
                dialog.style.margin = '0';
                dialog.style.maxWidth = '500px';
                dialog.style.width = '100%';
                dialog.style.pointerEvents = 'auto';
                
                // Add !important styles
                addImportantStyles(dialog, {
                    'position': 'absolute',
                    'top': '50%',
                    'left': '50%',
                    'transform': 'translate(-50%, -50%)',
                    'margin': '0'
                });
            }
            
            // Mark as processed
            modal.dataset.fixApplied = 'true';
            
            // Add event listeners
            modal.addEventListener('show.bs.modal', function() {
                document.body.style.overflow = 'hidden';
                document.body.style.paddingRight = '0';
                
                // Force position again
                this.style.position = 'fixed';
                this.style.display = 'block';
                
                // Fix dialog again
                const dialog = this.querySelector('.modal-dialog');
                if (dialog) {
                    dialog.style.position = 'absolute';
                    dialog.style.top = '50%';
                    dialog.style.left = '50%';
                    dialog.style.transform = 'translate(-50%, -50%)';
                }
                
                // Add hover protection
                addMouseEventHandlers(this);
            });
            
            modal.addEventListener('hidden.bs.modal', function() {
                document.body.style.overflow = '';
                document.body.style.paddingRight = '';
            });
            
            // Add hover protection for this modal
            addMouseEventHandlers(modal);
        });
    }
    
    // Helper function to add !important styles
    function addImportantStyles(element, styles) {
        // Create a style rule with !important for each property
        let styleText = '';
        for (const [property, value] of Object.entries(styles)) {
            styleText += `${property}: ${value} !important; `;
        }
        
        // Add the styles to the element
        const existingStyle = element.getAttribute('style') || '';
        element.setAttribute('style', existingStyle + styleText);
    }
    
    // 3. Fix backdrop
    function fixBackdrop() {
        setTimeout(function() {
            const backdrops = document.querySelectorAll('.modal-backdrop');
            backdrops.forEach(function(backdrop) {
                backdrop.style.position = 'fixed';
                backdrop.style.top = '0';
                backdrop.style.left = '0';
                backdrop.style.width = '100%';
                backdrop.style.height = '100%';
                backdrop.style.zIndex = '1040';
                
                // Add !important styles
                addImportantStyles(backdrop, {
                    'position': 'fixed',
                    'top': '0',
                    'left': '0',
                    'width': '100%',
                    'height': '100%'
                });
            });
        }, 0);
    }
    
    // 4. Initialize handlers for existing modals
    setupModalHandlers();
    
    // 5. Watch for new modals being added to the DOM
    const observer = new MutationObserver(function(mutations) {
        let newModalsFound = false;
        
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes) {
                mutation.addedNodes.forEach(function(node) {
                    // Check if the added node is a modal or contains modals
                    if (node.classList && node.classList.contains('modal')) {
                        newModalsFound = true;
                    } else if (node.querySelectorAll) {
                        const modals = node.querySelectorAll('.modal');
                        if (modals.length > 0) newModalsFound = true;
                    }
                    
                    // Also check for backdrop and fix it
                    if (node.classList && node.classList.contains('modal-backdrop')) {
                        fixBackdrop();
                    }
                });
            }
        });
        
        // If new modals were found, setup handlers for them
        if (newModalsFound) {
            setupModalHandlers();
        }
    });
    
    // Start observing
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
    
    // 6. Apply handlers when Bootstrap's JavaScript loads
    window.addEventListener('load', function() {
        setupModalHandlers();
        fixBackdrop();
    });
    
    // 7. Add a global CSS style to disable transitions on modals
    const styleSheet = document.createElement('style');
    styleSheet.type = 'text/css';
    styleSheet.innerHTML = `
        .modal, .modal-dialog, .modal-content, .modal-backdrop {
            transition: none !important;
            transform: none;
            animation: none !important;
        }
        .modal-dialog {
            transform: translate(-50%, -50%) !important;
            margin: 0 !important;
        }
    `;
    document.head.appendChild(styleSheet);
});