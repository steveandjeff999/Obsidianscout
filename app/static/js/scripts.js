/**
 * FRC Scouting Platform 
 * Team 5454 Scout 2026
 * Modern UI and Interaction JavaScript
 */

document.addEventListener('DOMContentLoaded', function() {
    // Register service worker for offline support
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js?v=2', { scope: '/' })
            .then(reg => {
                console.log('Service Worker registered:', reg.scope);
                // Force update check
                reg.update();
            })
            .catch(err => {
                console.warn('Service Worker registration failed:', err);
            });
    }
    
    // Initialize all tooltips
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    if (tooltipTriggerList.length) {
        [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
    }
    
    // Initialize all popovers
    const popoverTriggerList = document.querySelectorAll('[data-bs-toggle="popover"]');
    if (popoverTriggerList.length) {
        [...popoverTriggerList].map(popoverTriggerEl => new bootstrap.Popover(popoverTriggerEl));
    }
    
    // Initialize bootstrap toasts ONLY if they have the 'show' class
    const toastElList = document.querySelectorAll('.toast.show');
    if (toastElList.length) {
        [...toastElList].map(toastEl => {
            const toast = new bootstrap.Toast(toastEl, {
                autohide: true,
                delay: 5000
            });
            toast.show();
            // Add auto-removal after hiding
            toastEl.addEventListener('hidden.bs.toast', () => {
                setTimeout(() => {
                    toastEl.remove();
                }, 300);
            });
        });
    }
    
    // Dynamic page transitions
    initPageTransitions();
    
    // Counter buttons for scouting form
    initializeCounters();
    
    // Star rating system
    initializeRatings();
    
    // QR code generation
    const generateQRButton = document.getElementById('generateQR');
    if (generateQRButton) {
        generateQRButton.addEventListener('click', generateQRCode);
    }
    
    // Match period tabs with smooth transitions
    initializeMatchPeriodTabs();
    
    // Form validation with better user feedback
    validateForms();
    
    // Enable "Start Scouting" button when team and match are selected
    enableStartScoutingButton();
    
    // Initialize charts if visualization page is loaded
    if (document.querySelector('.chart-container')) {
        initializeCharts();
    }
    
    // Render Plotly graphs if any are present
    if (document.querySelector('.plotly-graph')) {
        renderPlotlyGraphs();
    }
    
    // Initialize points calculation if scouting form is present
    initializePointsCalculation();
    
    // Data table initialization
    initializeDataTables();
    
    // Add event listeners for the import/export functionality
    setupImportExport();
    
    // Fix modal positioning to prevent flashing/jumping
    setupModalBehavior();
    
    // Initialize search functionality
    setupSearch();
    
    // Handle loading states for buttons and forms
    setupLoadingBehavior();
    
    // Setup global keyboard shortcuts
    setupKeyboardShortcuts();
    
    // Initialize offline data manager
    setupOfflineDataManager();
    
    // Initialize scouting form with save functionality
    initScoutingForm();
    
    // Double-confirm delete logic for /data/manage
    let deleteConfirmTimeouts = {};
    document.querySelectorAll('.double-confirm-delete').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            const entryId = btn.getAttribute('data-entry-id');
            if (!deleteConfirmTimeouts[entryId]) {
                // First click: show notification
                showDeleteConfirmNotification(btn, entryId);
                deleteConfirmTimeouts[entryId] = setTimeout(() => {
                    deleteConfirmTimeouts[entryId] = null;
                    btn.textContent = 'Delete';
                    btn.classList.remove('btn-warning');
                    btn.classList.add('btn-danger');
                }, 5000);
                btn.textContent = 'Click again to confirm';
                btn.classList.remove('btn-danger');
                btn.classList.add('btn-warning');
            } else {
                // Second click: submit hidden form
                clearTimeout(deleteConfirmTimeouts[entryId]);
                deleteConfirmTimeouts[entryId] = null;
                // Find or create a hidden form and submit
                let form = document.getElementById('delete-form-' + entryId);
                if (!form) {
                    form = document.createElement('form');
                    form.method = 'POST';
                    form.action = `/data/delete/${entryId}`;
                    form.style.display = 'none';
                    form.id = 'delete-form-' + entryId;
                    document.body.appendChild(form);
                }
                form.submit();
            }
        });
    });
});

/**
 * Setup page transitions for smoother navigation experience
 */
function initPageTransitions() {
    // Add a class to the body when page is fully loaded
    document.body.classList.add('page-loaded');
    
    // Listen for link clicks and add page exit animation
    document.querySelectorAll('a:not([target="_blank"]):not([href^="#"]):not(.modal-trigger):not(.no-transition)').forEach(link => {
        link.addEventListener('click', function(e) {
            // Skip if modifier keys are pressed
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            
            const href = this.getAttribute('href');
            
            // Skip if it's an anchor or javascript link
            if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;
            
            // Skip API calls and downloads
            if (href.includes('/api/') || this.getAttribute('download')) return;
            
            e.preventDefault();
            
            // Show loading indicator
            document.body.classList.add('page-transition');
            
            // After a short delay, navigate to the new page
            setTimeout(() => {
                window.location.href = href;
            }, 300);
        });
    });
    
    // Add loading overlay functionality
    window.showLoadingOverlay = function() {
        const loadingOverlay = document.getElementById('loading-overlay');
        if (loadingOverlay) {
            loadingOverlay.classList.remove('d-none');
        }
    };
    
    window.hideLoadingOverlay = function() {
        const loadingOverlay = document.getElementById('loading-overlay');
        if (loadingOverlay) {
            loadingOverlay.classList.add('d-none');
        }
    };
}

/**
 * Initialize counter buttons for scouting form with improved UX
 */
function initializeCounters() {
    // Create a set to track which buttons we've already attached listeners to
    const processedButtons = new Set();
    
    // First handle buttons inside counter-container elements
    const counters = document.querySelectorAll('.counter-container');
    
    counters.forEach(counter => {
        const decrementBtn = counter.querySelector('.btn-decrement');
        const incrementBtn = counter.querySelector('.btn-increment');
        const countInput = counter.querySelector('input[type="number"]');
        
        if (!decrementBtn || !incrementBtn || !countInput) return;
        
        // Add these buttons to our processed set
        if (decrementBtn) processedButtons.add(decrementBtn);
        if (incrementBtn) processedButtons.add(incrementBtn);
        
        // Function to update counter value with animation
        const updateCounter = (newValue) => {
            // Add a pulse animation
            countInput.classList.add('counter-pulse');
            setTimeout(() => {
                countInput.classList.remove('counter-pulse');
            }, 300);
            
            countInput.value = newValue;
            countInput.dispatchEvent(new Event('change'));
            
            // Update disable state based on min/max
            if (countInput.min) {
                decrementBtn.disabled = parseInt(newValue) <= parseInt(countInput.min);
            }
            if (countInput.max) {
                incrementBtn.disabled = parseInt(newValue) >= parseInt(countInput.max);
            }
        };
        
        // Decrement button
        decrementBtn.addEventListener('click', () => {
            if (parseInt(countInput.value) > parseInt(countInput.min || 0)) {
                updateCounter(parseInt(countInput.value) - 1);
            }
        });
        
        // Increment button
        incrementBtn.addEventListener('click', () => {
            if (!countInput.max || parseInt(countInput.value) < parseInt(countInput.max)) {
                updateCounter(parseInt(countInput.value) + 1);
            }
        });
        
        // Set initial button state
        if (countInput.min) {
            decrementBtn.disabled = parseInt(countInput.value) <= parseInt(countInput.min);
        }
        if (countInput.max) {
            incrementBtn.disabled = parseInt(countInput.value) >= parseInt(countInput.max);
        }
        
        // Allow keyboard shortcuts for incrementing/decrementing
        countInput.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (!countInput.max || parseInt(countInput.value) < parseInt(countInput.max)) {
                    updateCounter(parseInt(countInput.value) + 1);
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (parseInt(countInput.value) > parseInt(countInput.min || 0)) {
                    updateCounter(parseInt(countInput.value) - 1);
                }
            }
        });
    });

    // Now handle buttons with data-target attributes that weren't already processed
    const targetCounters = document.querySelectorAll('[data-target]');
    targetCounters.forEach(btn => {
        if (!btn.classList.contains('btn-decrement') && !btn.classList.contains('btn-increment')) return;
        
        // Skip if we've already processed this button
        if (processedButtons.has(btn)) return;
        
        btn.addEventListener('click', () => {
            const targetId = btn.dataset.target;
            const input = document.getElementById(targetId);
            if (!input) return;
            
            let newValue = parseInt(input.value || 0);
            if (btn.classList.contains('btn-decrement') && newValue > 0) {
                newValue -= 1;
            } else if (btn.classList.contains('btn-increment')) {
                newValue += 1;
            }
            
            input.value = newValue;
            updatePointsCalculation();
            
            // Add visual feedback
            btn.classList.add('btn-pulse');
            setTimeout(() => btn.classList.remove('btn-pulse'), 300);
        });
    });
}

/**
 * Initialize star rating system with improved feedback
 */
function initializeRatings() {
    const ratingContainers = document.querySelectorAll('.rating-container');
    
    ratingContainers.forEach(container => {
        const stars = container.querySelectorAll('.rating-star');
        const hiddenInput = container.parentElement.querySelector('input[type="hidden"]');
        
        // Show current rating on load
        if (hiddenInput && hiddenInput.value) {
            const currentRating = parseInt(hiddenInput.value);
            stars.forEach((s, i) => {
                if (stars.length - i <= currentRating) {
                    s.classList.add('active');
                }
            });
        }
        
        // Update rating when clicking stars
        stars.forEach((star, index) => {
            // Show rating preview on hover
            star.addEventListener('mouseenter', () => {
                // Reset all stars
                stars.forEach(s => s.classList.remove('hover'));
                
                // Highlight stars up to the hovered one
                for (let i = 0; i <= index; i++) {
                    stars[i].classList.add('hover');
                }
            });
            
            // Reset on mouse leave
            container.addEventListener('mouseleave', () => {
                stars.forEach(s => s.classList.remove('hover'));
            });
            
            // Set rating on click
            star.addEventListener('click', () => {
                const rating = stars.length - index;
                
                // Update hidden input
                if (hiddenInput) {
                    hiddenInput.value = rating;
                    hiddenInput.dispatchEvent(new Event('change'));
                }
                
                // Update visual state with animation
                stars.forEach((s, i) => {
                    s.classList.remove('active');
                    s.classList.remove('animate-star');
                });
                
                setTimeout(() => {
                    stars.forEach((s, i) => {
                        if (i >= index) {
                            s.classList.add('active');
                            s.classList.add('animate-star');
                        }
                    });
                }, 10);
                
                // Show feedback toast
                showToast(`Rating set to ${rating} stars`, 'info');
            });
        });
    });
}

/**
 * Display toast notification
 * @param {string} message - The message to display
 * @param {string} type - The type of toast (success, danger, warning, info)
 * @param {number} duration - Duration in milliseconds to show the toast (default 3000)
 */
function showToast(message, type = 'info', duration = 3000) {
    const toastContainer = document.querySelector('.toast-container');
    if (!toastContainer) return;
    
    // Create new toast element
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.className = `toast show`;
    toast.id = toastId;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    
    // Toast content based on type
    let icon;
    switch (type) {
        case 'success': icon = 'fa-check-circle'; break;
        case 'danger': icon = 'fa-exclamation-triangle'; break;
        case 'warning': icon = 'fa-exclamation-circle'; break;
        default: icon = 'fa-info-circle';
    }
    
    toast.innerHTML = `
        <div class="toast-header bg-${type} ${['success', 'danger', 'primary'].includes(type) ? 'text-white' : ''}">
            <i class="fas ${icon} me-2"></i>
            <strong class="me-auto">Notification</strong>
            <small>Just now</small>
            <button type="button" class="btn-close ${['success', 'danger', 'primary'].includes(type) ? 'btn-close-white' : ''}" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
        <div class="toast-body">
            ${message}
        </div>
    `;
    
    // Add toast to container
    toastContainer.appendChild(toast);
    
    // Initialize Bootstrap toast
    const bsToast = new bootstrap.Toast(toast, {
        autohide: true,
        delay: duration
    });
    
    // Show the toast
    bsToast.show();
    
    // Remove from DOM after hiding
    toast.addEventListener('hidden.bs.toast', () => {
        setTimeout(() => {
            toast.remove();
        }, 300);
    });
}

/**
 * Generate QR code from form data with improved UX
 * Also supports offline mode by storing the data locally
 */
function generateQRCode() {
    const form = document.getElementById('scouting-form');
    const qrcodeContainer = document.getElementById('qrcode');
    
    if (!form || !qrcodeContainer) return;
    
    // Show loading animation
    qrcodeContainer.innerHTML = '<div class="d-flex justify-content-center my-4"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div></div>';
    
    // Check if QRCode library is available
    if (typeof QRCode === 'undefined') {
        console.error('QRCode library not loaded');
        qrcodeContainer.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Error: QR Code library not loaded. Please check your internet connection.
            </div>
        `;
        showToast('Failed to load QR Code library', 'danger');
        return;
    }
    
    // Slight delay to ensure loading animation is visible
    setTimeout(() => {
        try {
            // Clear loading animation
            qrcodeContainer.innerHTML = '';
            
            // Get all form data
            const formData = new FormData(form);
            const formObject = {};
            
            // Process all form fields
            formData.forEach((value, key) => {
                const element = form.elements[key];
                
                // Handle different input types appropriately
                if (element && element.type === 'checkbox') {
                    formObject[key] = element.checked;
                } else if (element && element.type === 'number' || (!isNaN(value) && value !== '')) {
                    // Convert numeric values
                    formObject[key] = Number(value);
                } else {
                    formObject[key] = value;
                }
            });
            
            // Ensure checkboxes that are unchecked are included as false
            const allCheckboxes = form.querySelectorAll('input[type="checkbox"]');
            allCheckboxes.forEach(checkbox => {
                if (!formObject.hasOwnProperty(checkbox.id)) {
                    formObject[checkbox.id] = false;
                }
            });
            
            // Add calculated points to the data
            const pointsElements = document.querySelectorAll('.points-display');
            pointsElements.forEach(element => {
                const metricId = element.dataset.metricId;
                if (metricId) {
                    const pointsValue = element.querySelector('.points-value');
                    if (pointsValue) {
                        formObject[metricId + '_points'] = parseInt(pointsValue.textContent || '0');
                    }
                }
            });

            // Defensive fallback: ensure scout_name is populated even if the input was left blank
            try {
                const scoutField = form.elements['scout_name'] || document.getElementById('scout_name');
                const fallbackScout = (scoutField && scoutField.placeholder) ? scoutField.placeholder : (scoutField && scoutField.value) ? scoutField.value : 'Unknown';
                if (!formObject.scout_name || (typeof formObject.scout_name === 'string' && formObject.scout_name.trim() === '')) {
                    formObject.scout_name = fallbackScout;
                }
            } catch (e) {
                // ignore any issues from missing elements
            }
            
            // Add metadata
            formObject.generated_at = new Date().toISOString();
            formObject.offline_generated = true;
            
            // For debugging
            console.log("Complete form data for QR:", formObject);
            
            // Create JSON string with complete form data
            const jsonString = JSON.stringify(formObject);
            
            // Log the size to help with debugging
            const jsonSizeKB = (jsonString.length / 1024).toFixed(2);
            console.log(`QR data size: ${jsonSizeKB} KB, ${jsonString.length} characters`);
            
            // Prepare container for larger QR code
            qrcodeContainer.style.minHeight = '300px';
            qrcodeContainer.style.width = '100%';
            qrcodeContainer.style.maxWidth = '400px';
            qrcodeContainer.style.margin = '0 auto';
            
            // Generate QR code with improved settings for detailed data
            try {
                // Clear previous content
                qrcodeContainer.innerHTML = '';
                
                // Use QRCode with improved settings for high-density QR codes
                new QRCode(qrcodeContainer, {
                    text: jsonString,
                    width: 400, // Increased size for better readability
                    height: 400,
                    colorDark: "#000000",
                    colorLight: "#ffffff",
                    correctLevel: QRCode.CorrectLevel.M, // Medium error correction for better scanning reliability
                    typeNumber: 0 // Auto-determine version based on data size
                });
                
                // Add CSS to ensure the QR code is centered and properly sized
                const qrImg = qrcodeContainer.querySelector('img');
                if (qrImg) {
                    qrImg.style.width = '100%';
                    qrImg.style.maxWidth = '400px'; // Match the QR code size
                    qrImg.style.height = 'auto';
                    qrImg.style.display = 'block';
                    qrImg.style.margin = '0 auto';
                    console.log("QR Code image created successfully");
                }
            } catch (qrError) {
                console.error('Error creating QR code with improved settings:', qrError);
                
                // If better quality version fails, try with less error correction
                try {
                    qrcodeContainer.innerHTML = ''; // Clear any partial results
                    
                    new QRCode(qrcodeContainer, {
                        text: jsonString,
                        width: 400,
                        height: 400,
                        colorDark: "#000000",
                        colorLight: "#ffffff",
                        correctLevel: QRCode.CorrectLevel.L // Lower error correction to fit more data
                    });
                    
                    // Apply same styling
                    const qrImg = qrcodeContainer.querySelector('img');
                    if (qrImg) {
                        qrImg.style.width = '100%';
                        qrImg.style.maxWidth = '400px';
                        qrImg.style.height = 'auto';
                        qrImg.style.display = 'block';
                        qrImg.style.margin = '0 auto';
                    }
                } catch (fallbackError) {
                    console.error('Error with fallback QR code generation:', fallbackError);
                    qrcodeContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <i class="fas fa-exclamation-triangle me-2"></i>
                            Error: Data too large for QR code. Please submit directly.
                        </div>
                    `;
                    showToast('Data too large for QR code', 'danger');
                    return;
                }
            }
            
            // Show download button and confirmation
            const downloadContainer = document.getElementById('qrDownloadContainer');
            if (downloadContainer) {
                downloadContainer.classList.remove('d-none');
                
                // Add download functionality
                const downloadButton = downloadContainer.querySelector('button');
                if (downloadButton) {
                    // Remove any existing event listeners
                    const newButton = downloadButton.cloneNode(true);
                    downloadButton.parentNode.replaceChild(newButton, downloadButton);
                    
                    // Add event listener to the new button
                    newButton.addEventListener('click', () => {
                        // Get the QR code image
                        const img = qrcodeContainer.querySelector('img');
                        if (img) {
                            // Create a temporary link
                            const link = document.createElement('a');
                            link.href = img.src;
                            link.download = `team_${formObject.team_id}_match_${formObject.match_id}_qr.png`;
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                        }
                    });
                }
            }
            
            // Show success message
            showToast('QR Code generated successfully', 'success');
            
        } catch (error) {
            console.error('Error generating QR Code:', error);
            qrcodeContainer.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    Error generating QR Code: ${error.message}
                </div>
            `;
            showToast('Failed to generate QR Code', 'danger');
        }
    }, 300);
}

/**
 * Initialize match period tabs with smooth transitions
 */
function initializeMatchPeriodTabs() {
    const tabs = document.querySelectorAll('.match-period-tab');
    const sections = document.querySelectorAll('.match-period-section');
    
    if (!tabs.length || !sections.length) return;
    
    // Helper function to update UI when switching tabs
    const switchTab = (targetId) => {
        // Update tab state
        tabs.forEach(t => {
            const isActive = t.getAttribute('data-target') === targetId;
            t.classList.toggle('active', isActive);
            
            // Add proper tab color based on period type
            if (isActive) {
                if (targetId.includes('auto')) {
                    t.classList.add('auto-tab');
                } else if (targetId.includes('teleop')) {
                    t.classList.add('teleop-tab');
                } else if (targetId.includes('endgame')) {
                    t.classList.add('endgame-tab');
                }
            } else {
                t.classList.remove('auto-tab', 'teleop-tab', 'endgame-tab');
            }
        });
        
        // Fade out all sections first
        sections.forEach(section => {
            if (section.id !== targetId) {
                section.style.opacity = '0';
                setTimeout(() => {
                    section.classList.add('d-none');
                }, 300);
            }
        });
        
        // Then fade in the target section after a short delay
        setTimeout(() => {
            const targetSection = document.getElementById(targetId);
            if (targetSection) {
                targetSection.classList.remove('d-none');
                setTimeout(() => {
                    targetSection.style.opacity = '1';
                }, 10);
                
                // Scroll into view if needed
                const rect = targetSection.getBoundingClientRect();
                if (rect.top < 0 || rect.bottom > window.innerHeight) {
                    targetSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
        }, 300);
    };
    
    // Set initial state for sections - making sure they have the transition CSS property
    sections.forEach(section => {
        section.style.transition = 'opacity 0.3s ease-in-out';
        if (!section.classList.contains('active')) {
            section.style.opacity = '0';
        } else {
            section.style.opacity = '1';
        }
    });
    
    // Add click handlers to tabs
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetId = tab.getAttribute('data-target');
            switchTab(targetId);
        });
    });
    
    // Set initial active tab if none is active
    if (!document.querySelector('.match-period-tab.active')) {
        const firstTab = tabs[0];
        if (firstTab) {
            firstTab.classList.add('active');
            const targetId = firstTab.getAttribute('data-target');
            switchTab(targetId);
        }
    }
}

/**
 * Improved form validation with better feedback
 */
function validateForms() {
    const forms = document.querySelectorAll('.needs-validation');
    
    Array.from(forms).forEach(form => {
        // Add custom validation styling as user types
        const inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            input.addEventListener('input', function () {
                // Clear previous error messages
                const feedbackElement = this.nextElementSibling?.classList.contains('invalid-feedback') 
                    ? this.nextElementSibling
                    : null;
                    
                if (feedbackElement) {
                    feedbackElement.textContent = '';
                }
                
                // Check validity as user types
                if (this.checkValidity()) {
                    this.classList.remove('is-invalid');
                    this.classList.add('is-valid');
                } else {
                    this.classList.remove('is-valid');
                    // Only add invalid class if user has started typing
                    if (this.value) {
                        this.classList.add('is-invalid');
                        
                        // Set custom error message based on validation type
                        if (feedbackElement) {
                            if (this.validity.valueMissing) {
                                feedbackElement.textContent = 'This field is required';
                            } else if (this.validity.typeMismatch) {
                                feedbackElement.textContent = `Please enter a valid ${this.type}`;
                            } else if (this.validity.rangeUnderflow) {
                                feedbackElement.textContent = `Value must be at least ${this.min}`;
                            } else if (this.validity.rangeOverflow) {
                                feedbackElement.textContent = `Value must be at most ${this.max}`;
                            }
                        }
                    }
                }
            });
        });

        // Handle form submission
        form.addEventListener('submit', event => {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
                
                // Find the first invalid element and focus it
                const invalidElement = form.querySelector(':invalid');
                if (invalidElement) {
                    invalidElement.focus();
                    
                    // Scroll to the invalid element if needed
                    invalidElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    
                    // Show toast message with error summary
                    const invalidCount = form.querySelectorAll(':invalid').length;
                    showToast(`Please fix ${invalidCount} form error${invalidCount !== 1 ? 's' : ''}`, 'warning');
                }
            } else {
                // Show saving indicator for better feedback
                const submitButton = form.querySelector('[type="submit"]');
                if (submitButton && !submitButton.classList.contains('no-loading-state')) {
                    const originalText = submitButton.innerHTML;
                    submitButton.disabled = true;
                    submitButton.innerHTML = `
                        <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
                        Saving...
                    `;
                    
                    // Reset button after a delay
                    setTimeout(() => {
                        submitButton.disabled = false;
                        submitButton.innerHTML = originalText;
                    }, 3000);
                }
            }
            
            form.classList.add('was-validated');
        }, false);
    });
}

/**
 * Enable "Start Scouting" button when team and match are selected
 */
function enableStartScoutingButton() {
    // Get button and necessary form elements
    const startButton = document.getElementById('start-scouting');
    if (!startButton) return;
    
    const teamSelector = document.getElementById('team-selector');
    const matchSelector = document.getElementById('match-selector');
    
    if (!teamSelector || !matchSelector) return;
    
    // Function to update button state
    const updateButtonState = () => {
        const teamSelected = teamSelector.value !== '';
        const matchSelected = matchSelector.value !== '';
        
        if (teamSelected && matchSelected) {
            startButton.disabled = false;
            startButton.classList.add('btn-pulse');
            setTimeout(() => {
                startButton.classList.remove('btn-pulse');
            }, 500);
        } else {
            startButton.disabled = true;
        }
        
        // Update visual indicators
        teamSelector.classList.toggle('is-valid', teamSelected);
        matchSelector.classList.toggle('is-valid', matchSelected);
        
        // Show focus indicator on the next field that needs completion
        if (!teamSelected) {
            teamSelector.classList.add('needs-attention');
            matchSelector.classList.remove('needs-attention');
        } else if (!matchSelected) {
            teamSelector.classList.remove('needs-attention');
            matchSelector.classList.add('needs-attention');
        } else {
            teamSelector.classList.remove('needs-attention');
            matchSelector.classList.remove('needs-attention');
        }
    };
    
    // Add change event listeners
    teamSelector.addEventListener('change', updateButtonState);
    matchSelector.addEventListener('change', updateButtonState);
    
    // Initial state check
    updateButtonState();
}

/**
 * Calculate points based on formula from game config
 * @param {string} formula - Formula string from game config
 * @param {Object} data - Object containing the values to use in the formula
 * @returns {number} Calculated points
 */
function calculatePoints(formula, data) {
    if (!formula || !data) return 0;
    
    try {
        // If we have a formula that references period durations, ensure we have them
        if (formula.includes('duration_seconds') || formula.includes('scoring_frequency')) {
            // Get duration values from data-attributes if available
            const autoDuration = parseInt(document.querySelector('meta[name="auto_duration"]')?.getAttribute('content') || '15');
            const teleopDuration = parseInt(document.querySelector('meta[name="teleop_duration"]')?.getAttribute('content') || '120');
            const endgameDuration = parseInt(document.querySelector('meta[name="endgame_duration"]')?.getAttribute('content') || '30');
            
            // Add these to the data object for formula calculation
            data.auto_duration_seconds = autoDuration;
            data.teleop_duration_seconds = teleopDuration;
            data.endgame_duration_seconds = endgameDuration;
            data.total_match_duration = autoDuration + teleopDuration + endgameDuration;
        }
        
        // Handle special case for auto-generated formulas
        if (formula === 'auto_generated') {
            // For metrics that use dynamic point calculations
            if (data.metric_id === 'auto_points') {
                return calculatePeriodPoints('auto', data);
            } else if (data.metric_id === 'teleop_points') {
                return calculatePeriodPoints('teleop', data);
            } else if (data.metric_id === 'endgame_points') {
                return calculatePeriodPoints('endgame', data);
            } else if (data.metric_id === 'total_points') {
                return calculatePeriodPoints('auto', data) + 
                       calculatePeriodPoints('teleop', data) + 
                       calculatePeriodPoints('endgame', data);
            }
        }
        
        // Create a function that evaluates the formula with the data
        let evalFunction = new Function(...Object.keys(data), `return ${formula}`);
        return evalFunction(...Object.values(data));
    } catch (error) {
        console.error('Error calculating points:', error);
        return 0;
    }
}

/**
 * Calculate points for a specific period using the config point values
 * @param {string} period - The period to calculate points for ('auto', 'teleop', or 'endgame')
 * @param {Object} data - Form data object
 * @returns {number} - Total points for the period
 */
function calculatePeriodPoints(period, data) {
    let points = 0;
    
    // Use the global GAME_CONFIG that was passed via the script tag in base.html
    if (!window.GAME_CONFIG) {
        console.error('Game configuration not found');
        return 0;
    }
    
    try {
        // Get scoring elements for the period
        const periodConfig = window.GAME_CONFIG[`${period}_period`];
        if (!periodConfig || !periodConfig.scoring_elements) return 0;
        
        // Calculate points for each scoring element
        periodConfig.scoring_elements.forEach(element => {
            const elementId = element.id;
            
            // Skip if element is not in the form data
            if (!(elementId in data)) return;
            
            // Handle different element types
            if (element.type === 'boolean' && element.points) {
                // Boolean elements
                if (data[elementId] === true) {
                    points += element.points;
                }
            } else if (element.type === 'counter' && element.points) {
                // Counter elements with direct points
                points += data[elementId] * element.points;
            } else if (element.type === 'select' && element.points) {
                // Select elements with points object
                const selectedValue = data[elementId];
                if (typeof element.points === 'object' && selectedValue in element.points) {
                    points += element.points[selectedValue];
                }
            } else if (element.game_piece_id) {
                // Game piece elements without direct points
                for (const gamePiece of window.GAME_CONFIG.game_pieces || []) {
                    if (gamePiece.id === element.game_piece_id) {
                        if (element.bonus) {
                            points += data[elementId] * gamePiece.bonus_points;
                        } else if (period === 'auto') {
                            points += data[elementId] * gamePiece.auto_points;
                        } else if (period === 'teleop') {
                            points += data[elementId] * gamePiece.teleop_points;
                        }
                        break;
                    }
                }
            }
        });
        
        return points;
    } catch (error) {
        console.error(`Error calculating ${period} points:`, error);
        return 0;
    }
}

/**
 * Initialize points calculation on the scouting form with enhanced UI feedback
 */
function initializePointsCalculation() {
    const scoutingForm = document.getElementById('scouting-form');
    
    if (!scoutingForm) return;
    
    // Get all inputs that might affect points
    const allInputs = scoutingForm.querySelectorAll('input, select');
    
    // Add change event listener for realtime updates
    allInputs.forEach(input => {
        input.addEventListener('change', () => {
            updatePointsCalculation();
            
            // Add visual feedback on change
            const pointsDisplays = document.querySelectorAll('.points-display');
            pointsDisplays.forEach(display => {
                display.classList.add('points-updating');
                setTimeout(() => {
                    display.classList.remove('points-updating');
                }, 500);
            });
        });
    });
    
    // Initial calculation
    updatePointsCalculation();
}

/**
 * Update points calculation when form inputs change
 */
function updatePointsCalculation() {
    const scoutingForm = document.getElementById('scouting-form');
    const pointsContainers = document.querySelectorAll('.points-display');
    
    if (!scoutingForm || !pointsContainers.length) return;
    
    // Get all form data
    const formData = new FormData(scoutingForm);
    const data = {};
    
    // Convert form data to an object
    for (const [key, value] of formData.entries()) {
        // Convert boolean values from "on" to true
        if (value === "on") {
            data[key] = true;
        } 
        // Convert numeric values
        else if (!isNaN(value)) {
            data[key] = Number(value);
        } 
        // Keep string values
        else {
            data[key] = value;
        }
    }
    
    // Set default boolean values to false if not in the form data
    document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        if (!data.hasOwnProperty(checkbox.id)) {
            data[checkbox.id] = false;
        }
    });
    
    // Calculate points for each container that has a formula
    pointsContainers.forEach(container => {
        const formula = container.dataset.formula;
        const metricId = container.dataset.metricId;
        const pointsValue = container.querySelector('.points-value');
        
        if (formula && pointsValue) {
            // Add metric ID to data object if available
            if (metricId) {
                data.metric_id = metricId;
            }
            
            const points = calculatePoints(formula, data);
            pointsValue.textContent = points;
        }
    });
    
    // Calculate total points
    const totalPointsContainer = document.getElementById('total-points');
    if (totalPointsContainer) {
        const totalFormula = totalPointsContainer.dataset.formula;
        const metricId = totalPointsContainer.dataset.metricId;
        
        if (totalFormula) {
            // Add metric ID to data object if available
            if (metricId) {
                data.metric_id = metricId;
            }
            
            const totalPoints = calculatePoints(totalFormula, data);
            const totalPointsValue = totalPointsContainer.querySelector('.points-value');
            if (totalPointsValue) {
                totalPointsValue.textContent = totalPoints;
            }
        }
    }
}

/**
 * Initialize data tables with search, sort and pagination
 */
function initializeDataTables() {
    // Check if DataTables library is available
    if (typeof $.fn.DataTable === 'undefined') return;
    
    const tables = document.querySelectorAll('.data-table');
    
    tables.forEach(table => {
        // Initialize with custom options
        $(table).DataTable({
            responsive: true,
            language: {
                search: '<i class="fas fa-search"></i>',
                searchPlaceholder: 'Search...',
                lengthMenu: 'Show _MENU_ entries',
                info: 'Showing _START_ to _END_ of _TOTAL_ entries',
                paginate: {
                    first: '<i class="fas fa-angle-double-left"></i>',
                    previous: '<i class="fas fa-angle-left"></i>',
                    next: '<i class="fas fa-angle-right"></i>',
                    last: '<i class="fas fa-angle-double-right"></i>'
                }
            },
            dom: '<"row"<"col-md-6"l><"col-md-6"f>><"table-responsive"t><"row"<"col-md-6"i><"col-md-6"p>>',
            pageLength: 10,
            lengthMenu: [[5, 10, 25, 50, -1], [5, 10, 25, 50, 'All']]
        });
    });
}

/**
 * Set up proper modal behavior
 */
function setupModalBehavior() {
    const modals = document.querySelectorAll('.modal');
    
    modals.forEach(modal => {
        // Fix scrollbar jump when modal opens
        modal.addEventListener('show.bs.modal', function() {
            const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
            document.body.style.paddingRight = scrollbarWidth + 'px';
            document.body.style.overflow = 'hidden';
        });
        
        // Reset when modal closes
        modal.addEventListener('hidden.bs.modal', function() {
            document.body.style.paddingRight = '';
            document.body.style.overflow = '';
        });
        
        // Prevent modal from closing when clicking inside modal content
        const modalContent = modal.querySelector('.modal-content');
        if (modalContent) {
            modalContent.addEventListener('click', function(event) {
                event.stopPropagation();
            });
        }
        
        // Add escape key listener
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && modal.classList.contains('show')) {
                const bsModal = bootstrap.Modal.getInstance(modal);
                if (bsModal) bsModal.hide();
            }
        });
    });
}

/**
 * Setup global search functionality
 */
function setupSearch() {
    const globalSearchInput = document.getElementById('global-search');
    const searchResultsContainer = document.getElementById('search-results');
    
    if (!globalSearchInput || !searchResultsContainer) return;
    
    // Debounce function to avoid excessive requests
    let searchTimeout;
    
    globalSearchInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        const query = this.value.trim();
        
        if (query.length < 2) {
            searchResultsContainer.innerHTML = '';
            searchResultsContainer.classList.add('d-none');
            return;
        }
        
        // Set timeout for debounce
        searchTimeout = setTimeout(() => {
            // Show loading indicator
            searchResultsContainer.innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm" role="status"></div><div class="mt-2">Searching...</div></div>';
            searchResultsContainer.classList.remove('d-none');
            
            // Fetch search results
            fetchWithOfflineFallback(`/api/search?q=${encodeURIComponent(query)}`)
                .then(data => {
                    // Generate results HTML
                    if (data.results && data.results.length) {
                        // Format and display results
                        let resultsHtml = '<div class="list-group">';
                        data.results.forEach(result => {
                            resultsHtml += `
                                <a href="${result.url}" class="list-group-item list-group-item-action">
                                    <div class="d-flex w-100 justify-content-between">
                                        <h6 class="mb-1">${result.title}</h6>
                                        <small class="text-muted">${result.type}</small>
                                    </div>
                                    <p class="mb-1 small">${result.description || ''}</p>
                                </a>
                            `;
                        });
                        resultsHtml += '</div>';
                        searchResultsContainer.innerHTML = resultsHtml;
                    } else {
                        searchResultsContainer.innerHTML = '<div class="p-3 text-center">No results found</div>';
                    }
                })
                .catch(error => {
                    console.error('Search error:', error);
                    searchResultsContainer.innerHTML = '<div class="p-3 text-center text-danger">Error performing search</div>';
                });
        }, 300);
    });
    
    // Close search results when clicking outside
    document.addEventListener('click', function(event) {
        if (!searchResultsContainer.contains(event.target) && event.target !== globalSearchInput) {
            searchResultsContainer.classList.add('d-none');
        }
    });
    
    // Clear search on Escape key
    globalSearchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            this.value = '';
            searchResultsContainer.innerHTML = '';
            searchResultsContainer.classList.add('d-none');
        }
    });
}

/**
 * Setup loading behavior for buttons and forms
 */
function setupLoadingBehavior() {
    // Handle loading state for buttons with data-loading-text attribute
    document.querySelectorAll('[data-loading-text]').forEach(button => {
        button.addEventListener('click', function() {
            if (this.classList.contains('no-loading-state') || this.disabled) return;
            
            const loadingText = this.getAttribute('data-loading-text');
            const originalHtml = this.innerHTML;
            const originalWidth = this.offsetWidth;
            
            // Set minimum width to prevent button size change
            this.style.minWidth = originalWidth + 'px';
            
            // Save original HTML for restoration
            this.setAttribute('data-original-html', originalHtml);
            
            // Update button with loading state
            this.disabled = true;
            this.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${loadingText || 'Loading...'}`;
            
            // Restore original state after action completes
            // This requires manually calling resetLoadingButton(buttonElement) from your AJAX handlers
        });
    });
    
    // Make this function globally available
    window.resetLoadingButton = function(button) {
        if (!button) return;
        
        const originalHtml = button.getAttribute('data-original-html');
        if (originalHtml) {
            button.innerHTML = originalHtml;
            button.disabled = false;
        }
    };
}

/**
 * Setup keyboard shortcuts for common actions
 */
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        // Only handle keyboard shortcuts when not in an input field
        if (e.target.matches('input, textarea, select')) return;
        
        // Alt+S - Go to Scouting page
        if (e.altKey && e.key === 's') {
            e.preventDefault();
            window.location.href = '/scouting';
        }
        
        // Alt+D - Go to Dashboard
        if (e.altKey && e.key === 'd') {
            e.preventDefault(); 
            window.location.href = '/';
        }
        
        // Alt+V - Go to Visualization
        if (e.altKey && e.key === 'v') {
            e.preventDefault();
            window.location.href = '/visualization';
        }
        
        // Alt+T - Go to Teams
        if (e.altKey && e.key === 't') {
            e.preventDefault();
            window.location.href = '/teams';
        }
        
        // Alt+M - Go to Matches
        if (e.altKey && e.key === 'm') {
            e.preventDefault();
            window.location.href = '/matches';
        }
        
        // Alt+C - Go to Configuration
        if (e.altKey && e.key === 'c') {
            e.preventDefault();
            window.location.href = '/config';
        }
        
        // ? - Show keyboard shortcuts help
        if (e.key === '?') {
            e.preventDefault();
            showKeyboardShortcutsHelp();
        }
    });
}

/**
 * Display keyboard shortcuts help modal
 */
function showKeyboardShortcutsHelp() {
    // Create modal if it doesn't exist yet
    let modal = document.getElementById('keyboard-shortcuts-modal');
    
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'keyboard-shortcuts-modal';
        modal.className = 'modal fade';
        modal.tabIndex = '-1';
        modal.setAttribute('aria-hidden', 'true');
        
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Keyboard Shortcuts</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <table class="table table-sm">
                            <thead>
                                <tr>
                                    <th>Shortcut</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>S</kbd></td>
                                    <td>Go to Scouting</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>D</kbd></td>
                                    <td>Go to Dashboard</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>V</kbd></td>
                                    <td>Go to Visualization</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>T</kbd></td>
                                    <td>Go to Teams</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>M</kbd></td>
                                    <td>Go to Matches</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>C</kbd></td>
                                    <td>Go to Configuration</td>
                                </tr>
                                <tr>
                                    <td><kbd>?</kbd></td>
                                    <td>Show this help</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
    }
    
    // Show the modal
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}

/**
 * Render Plotly graphs from data attributes
 * Used in the visualization pages
 */
function renderPlotlyGraphs() {
    // Check if Plotly is available
    if (typeof Plotly === 'undefined') {
        console.error('Plotly is not loaded. Make sure to include Plotly.js before calling renderPlotlyGraphs()');
        return;
    }
    
    // Find all elements with plotly-graph class
    const graphElements = document.querySelectorAll('.plotly-graph');
    
    console.log(`Found ${graphElements.length} graph elements to render`);
    
    graphElements.forEach(element => {
        // Get graph data from data attribute
        try {
            // Parse the JSON data from the data-graph attribute
            const graphJson = element.getAttribute('data-graph');
            if (!graphJson) {
                console.error('No graph data found for element:', element.id);
                element.innerHTML = `
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-circle me-2"></i>
                        No graph data available.
                    </div>`;
                return;
            }
            
            console.log(`Rendering graph for ${element.id}, data length: ${graphJson.length}`);
            
            // Parse the JSON data - handle potential HTML unescaping
            let parsedData;
            try {
                parsedData = JSON.parse(graphJson);
            } catch (parseError) {
                console.error('JSON parse error, trying to fix escaped JSON:', parseError);
                // Sometimes the JSON gets HTML escaped when rendered in templates
                const unescapedJson = graphJson
                    .replace(/&quot;/g, '"')
                    .replace(/&#39;/g, "'")
                    .replace(/&lt;/g, '<')
                    .replace(/&gt;/g, '>');
                    
                try {
                    parsedData = JSON.parse(unescapedJson);
                } catch (secondError) {
                    console.error('Failed to parse JSON even after unescaping:', secondError);
                    // Add debugging information
                    console.debug('Raw JSON data:', graphJson);
                    throw new Error('Failed to parse graph data');
                }
            }
            
            // Check which format we're dealing with
            if (parsedData.data && parsedData.layout) {
                // Our custom format with data and layout properties
                console.log('Using custom format with data and layout properties');
                Plotly.newPlot(element.id, parsedData.data, parsedData.layout, {
                    responsive: true,
                    displayModeBar: true, 
                    displaylogo: false
                });
            } else {
                // Using plotly.io.to_json format
                console.log('Using plotly.io.to_json format');
                Plotly.newPlot(element.id, parsedData, {
                    responsive: true,
                    displayModeBar: true, 
                    displaylogo: false
                });
            }
            
            console.log(`Successfully rendered graph for ${element.id}`);
        } catch (error) {
            console.error('Error rendering Plotly graph for element', element.id, ':', error);
            
            // Create a more informative error indicator in the graph container
            element.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle me-2"></i>
                    Error loading graph: ${error.message}
                </div>`;
            
            // Add a debug button that shows the data when clicked
            const debugBtn = document.createElement('button');
            debugBtn.className = 'btn btn-sm btn-outline-danger mt-2';
            debugBtn.textContent = 'Debug Info';
            debugBtn.onclick = () => {
                console.log(`Debug data for ${element.id}:`, element.getAttribute('data-graph'));
                alert('Debug info logged to console. Press F12 to view.');
            };
            element.querySelector('.alert').appendChild(debugBtn);
        }
    });
}

/**
 * Setup import and export functionality
 * Handles file uploads, Excel imports/exports, and QR code scanning
 */
function setupImportExport() {
    // File upload form handling
    const fileInputs = document.querySelectorAll('.custom-file-input');
    fileInputs.forEach(input => {
        input.addEventListener('change', function() {
            // Update the file name display
            const fileName = this.files[0]?.name || 'Choose file...';
            const fileLabel = this.nextElementSibling;
            if (fileLabel) {
                fileLabel.textContent = fileName;
            }
            
            // Enable submit button if file is selected
            const submitBtn = this.closest('form')?.querySelector('[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = !this.files.length;
                
                if (this.files.length) {
                    submitBtn.classList.add('btn-success');
                    submitBtn.classList.remove('btn-secondary');
                } else {
                    submitBtn.classList.remove('btn-success');
                    submitBtn.classList.add('btn-secondary');
                }
            }
        });
    });
    
    // QR Code scanner functionality
    const qrScannerContainer = document.getElementById('qr-scanner-container');
    const qrResult = document.getElementById('qr-result');
    const startScanButton = document.getElementById('start-scan');
    const stopScanButton = document.getElementById('stop-scan');
    
    // Initialize QR scanner if all elements exist
    if (qrScannerContainer && startScanButton && stopScanButton) {
        let scanner = null;
        
        // Start scanning when button clicked
        startScanButton.addEventListener('click', function() {
            // Show the scanner container
            qrScannerContainer.classList.remove('d-none');
            this.disabled = true;
            stopScanButton.disabled = false;
            
            // Clear any previous results
            if (qrResult) {
                qrResult.innerHTML = '';
                qrResult.classList.add('d-none');
            }
            
            // Initialize scanner if needed
            // Enhanced QR Code scanner configuration for better detection
            if (!scanner && window.Html5QrcodeScanner) {
                scanner = new Html5QrcodeScanner('qr-reader', {
                    fps: 15, // Increase frames per second for faster detection
                    qrbox: { width: 300, height: 300 }, // Larger scanning area for better accuracy
                    disableFlip: false, // Allow flipping for mirrored QR codes
                    aspectRatio: 1.0, // Maintain square aspect ratio
                    formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE],
                    experimentalFeatures: {
                        useBarCodeDetectorIfSupported: true // Use advanced barcode detection if available
                    },
                    rememberLastUsedCamera: true, // Automatically use the last selected camera
                    supportedScanTypes: [Html5QrcodeScanType.SCAN_TYPE_CAMERA]
                });

                // On successful scan
                scanner.render((decodedText) => {
                    console.log("QR Code detected:", decodedText); // Log detected QR code for debugging
                    // ...existing code for processing the QR code...
                }, (errorMessage) => {
                    console.warn("QR scanning error:", errorMessage); // Log warnings for missed scans
                });
            } else if (scanner) {
                scanner.render((decodedText) => {
                    // Same handler as above
                }, (errorMessage) => {
                    console.error('QR scanning error:', errorMessage);
                });
            }
        });
        
        // Stop scanning when button clicked
        stopScanButton.addEventListener('click', function() {
            if (scanner) {
                scanner.clear();
            }
            
            // Reset button states
            startScanButton.disabled = false;
            this.disabled = true;
            
            // Hide scanner container
            qrScannerContainer.classList.add('d-none');
        });
    }
    
    // Excel export button handling
    const exportButtons = document.querySelectorAll('.export-excel-btn');
    exportButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            // Show loading state
            const originalText = this.innerHTML;
            this.disabled = true;
            this.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status"></span>Exporting...`;
            
            // Get export parameters
            const exportType = this.dataset.exportType || 'all';
            const teamId = this.dataset.teamId || '';
            const matchId = this.dataset.matchId || '';
            const eventId = this.dataset.eventId || '';
            
            // Build query params
            let params = `type=${exportType}`;
            if (teamId) params += `&team_id=${teamId}`;
            if (matchId) params += `&match_id=${matchId}`;
            if (eventId) params += `&event_id=${eventId}`;
            
            // Trigger download
            window.location.href = `/data/export_excel?${params}`;
            
            // Reset button after a delay
            setTimeout(() => {
                this.disabled = false;
                this.innerHTML = originalText;
            }, 1500);
        });
    });
    
    // Excel import form handling
    const excelImportForm = document.getElementById('excel-import-form');
    if (excelImportForm) {
        excelImportForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Get the file input
            const fileInput = this.querySelector('input[type="file"]');
            if (!fileInput || !fileInput.files.length) {
                showToast('Please select an Excel file to import', 'warning');
                return;
            }
            
            // Show loading overlay
            window.showLoadingOverlay();
            
            // Create form data for upload
            const formData = new FormData(this);
            
            // Submit the form using fetch
            fetch(this.action, {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                // Hide loading overlay
                window.hideLoadingOverlay();
                
                if (data.success) {
                    showToast('Excel data imported successfully!', 'success');
                    
                    // Show import results
                    const resultsContainer = document.getElementById('import-results');
                    if (resultsContainer && data.results) {
                        resultsContainer.innerHTML = `
                            <div class="alert alert-success mb-4">
                                <i class="fas fa-check-circle me-2"></i>
                                Import completed successfully
                            </div>
                            <div class="card">
                                <div class="card-header">
                                    <h5 class="mb-0">Import Results</h5>
                                </div>
                                <div class="card-body">
                                    <dl class="row">
                                        <dt class="col-sm-4">Teams imported:</dt>
                                        <dd class="col-sm-8">${data.results.teams || 0}</dd>
                                        
                                        <dt class="col-sm-4">Matches imported:</dt>
                                        <dd class="col-sm-8">${data.results.matches || 0}</dd>
                                        
                                        <dt class="col-sm-4">Scouting records imported:</dt>
                                        <dd class="col-sm-8">${data.results.scouting || 0}</dd>
                                        
                                        <dt class="col-sm-4">Total records:</dt>
                                        <dd class="col-sm-8">${data.results.total || 0}</dd>
                                    </dl>
                                </div>
                            </div>
                        `;
                    }
                    
                    // Reset form
                    this.reset();
                    const fileLabel = fileInput.nextElementSibling;
                    if (fileLabel) {
                        fileLabel.textContent = 'Choose file...';
                    }
                } else {
                    // Show error message
                    showToast(`Error: ${data.message || 'Import failed'}`, 'danger');
                }
            })
            .catch(error => {
                console.error('Error importing Excel data:', error);
                window.hideLoadingOverlay();
                showToast('Server error while importing data', 'danger');
            });
        });
    }
}

/**
 * Manage offline scouting data storage and synchronization
 * This function handles the UI for the offline data management section
 */
function setupOfflineDataManager() {
    const offlineDataContainer = document.getElementById('offline-data-container');
    if (!offlineDataContainer) return;
    
    // Function to refresh the list of offline entries
    const refreshOfflineEntries = () => {
        try {
            // Get stored entries index
            const offlineScoutingIndex = JSON.parse(localStorage.getItem('offline_scouting_index') || '[]');
            
            // If no entries, show empty state
            if (offlineScoutingIndex.length === 0) {
                offlineDataContainer.innerHTML = `
                    <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>
                        No offline scouting data available.
                    </div>
                `;
                return;
            }
            
            // Sort entries by timestamp (newest first)
            offlineScoutingIndex.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
            
            // Create table of entries
            let html = `
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead>
                            <tr>
                                <th>Team</th>
                                <th>Match</th>
                                <th>Date/Time</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            offlineScoutingIndex.forEach(entry => {
                const date = new Date(entry.timestamp);
                const formattedDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
                
                html += `
                    <tr data-storage-key="${entry.storage_key}">
                        <td>${entry.team_number}</td>
                        <td>${entry.match_number}</td>
                        <td>${formattedDate}</td>
                        <td>
                            <div class="btn-group btn-group-sm">
                                <button type="button" class="btn btn-primary view-offline-data" title="View">
                                    <i class="fas fa-eye"></i>
                                </button>
                                <button type="button" class="btn btn-success sync-offline-data" title="Sync">
                                    <i class="fas fa-sync"></i>
                                </button>
                                <button type="button" class="btn btn-danger delete-offline-data" title="Delete">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            });
            
            html += `
                        </tbody>
                    </table>
                </div>
                <div class="d-flex justify-content-end mt-3">
                    <button type="button" class="btn btn-primary" id="sync-all-offline-data">
                        <i class="fas fa-sync me-2"></i> Sync All Offline Data
                    </button>
                </div>
            `;
            
            offlineDataContainer.innerHTML = html;
            
            // Add event listeners to buttons
            document.querySelectorAll('.view-offline-data').forEach(button => {
                button.addEventListener('click', function() {
                    const storageKey = this.closest('tr').dataset.storageKey;
                    viewOfflineData(storageKey);
                });
            });
            
            document.querySelectorAll('.sync-offline-data').forEach(button => {
                button.addEventListener('click', function() {
                    const storageKey = this.closest('tr').dataset.storageKey;
                    syncOfflineData(storageKey);
                });
            });
            
            document.querySelectorAll('.delete-offline-data').forEach(button => {
                button.addEventListener('click', function() {
                    const storageKey = this.closest('tr').dataset.storageKey;
                    deleteOfflineData(storageKey);
                });
            });
            
            const syncAllButton = document.getElementById('sync-all-offline-data');
            if (syncAllButton) {
                syncAllButton.addEventListener('click', syncAllOfflineData);
            }
        } catch (error) {
            console.error('Error refreshing offline entries:', error);
            offlineDataContainer.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    Error loading offline data: ${error.message}
                </div>
            `;
        }
    };
    
    // Function to view offline data
    const viewOfflineData = (storageKey) => {
        try {
            const data = JSON.parse(localStorage.getItem(storageKey));
            if (!data) {
                showToast('Data not found in local storage', 'error');
                return;
            }
            
            // Create and show modal with data
            let modal = document.getElementById('offline-data-modal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'offline-data-modal';
                modal.className = 'modal fade';
                modal.setAttribute('tabindex', '-1');
                modal.innerHTML = `
                    <div class="modal-dialog modal-lg">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Offline Scouting Data</h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                            </div>
                            <div class="modal-body">
                                <pre class="bg-light p-3 rounded" style="max-height: 400px; overflow-y: auto;"></pre>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                            </div>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
            }
            
            // Populate with data
            const pre = modal.querySelector('pre');
            pre.textContent = JSON.stringify(data, null, 2);
            
            // Show modal
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
            
        } catch (error) {
            console.error('Error viewing offline data:', error);
            showToast('Error viewing data: ' + error.message, 'danger');
        }
    };
    
    // Function to sync a single offline entry
    const syncOfflineData = async (storageKey) => {
        try {
            const data = JSON.parse(localStorage.getItem(storageKey));
            if (!data) {
                showToast('Data not found in local storage', 'error');
                return;
            }
            
            // Check connectivity
            if (!navigator.onLine) {
                showToast('Cannot sync while offline', 'warning');
                return;
            }
            
            const button = document.querySelector(`tr[data-storage-key="${storageKey}"] .sync-offline-data`);
            if (button) {
                const originalHtml = button.innerHTML;
                button.disabled = true;
                button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
                
                try {
                    // Submit to server
                    const response = await fetch('/scouting/api/submit_offline', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(data)
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        // Remove from local storage
                        removeOfflineEntry(storageKey);
                        showToast('Data synchronized successfully!', 'success');
                        
                        // Refresh the list
                        refreshOfflineEntries();
                    } else {
                        button.disabled = false;
                        button.innerHTML = originalHtml;
                        showToast(`Error synchronizing: ${result.message}`, 'danger');
                    }
                } catch (error) {
                    button.disabled = false;
                    button.innerHTML = originalHtml;
                    showToast('Error synchronizing data with server', 'danger');
                    console.error('Sync error:', error);
                }
            }
        } catch (error) {
            console.error('Error syncing offline data:', error);
            showToast('Error preparing data for sync: ' + error.message, 'danger');
        }
    };
    
    // Function to delete offline data
    const deleteOfflineData = (storageKey) => {
        // Confirm before deleting
        if (confirm('Are you sure you want to delete this offline entry?')) {
            try {
                removeOfflineEntry(storageKey);
                showToast('Offline entry deleted', 'success');
                refreshOfflineEntries();
            } catch (error) {
                console.error('Error deleting offline data:', error);
                showToast('Error deleting entry: ' + error.message, 'danger');
            }
        }
    };
    
    // Helper function to remove an entry from local storage
    const removeOfflineEntry = (storageKey) => {
        // Remove from index
        let offlineScoutingIndex = JSON.parse(localStorage.getItem('offline_scouting_index') || '[]');
        offlineScoutingIndex = offlineScoutingIndex.filter(entry => entry.storage_key !== storageKey);
        localStorage.setItem('offline_scouting_index', JSON.stringify(offlineScoutingIndex));
        
        // Remove actual data
        localStorage.removeItem(storageKey);
    };
    
    // Function to sync all offline data
    const syncAllOfflineData = async () => {
        const offlineScoutingIndex = JSON.parse(localStorage.getItem('offline_scouting_index') || '[]');
        if (offlineScoutingIndex.length === 0) {
            showToast('No offline entries to sync', 'info');
            return;
        }
        
        // Check connectivity
        if (!navigator.onLine) {
            showToast('Cannot sync while offline', 'warning');
            return;
        }
        
        const syncAllButton = document.getElementById('sync-all-offline-data');
        if (syncAllButton) {
            const originalHtml = syncAllButton.innerHTML;
            syncAllButton.disabled = true;
            syncAllButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Syncing...';
            
            // Count for stats
            let success = 0;
            let failed = 0;
            
            // Process each entry
            for (const entry of offlineScoutingIndex) {
                try {
                    const data = JSON.parse(localStorage.getItem(entry.storage_key));
                    if (!data) continue;
                    
                    // Submit to server
                    const response = await fetch('/scouting/api/submit_offline', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(data)
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        // Remove from local storage
                        localStorage.removeItem(entry.storage_key);
                        success++;
                    } else {
                        failed++;
                        console.error('Error syncing entry:', result.message);
                    }
                } catch (error) {
                    failed++;
                    console.error('Error processing entry:', error);
                }
            }
            
            // Update index to remove synced entries
            let updatedIndex = [];
            if (failed > 0) {
                // If any failed, rebuild the index from remaining entries
                updatedIndex = [];
                offlineScoutingIndex.forEach(entry => {
                    if (localStorage.getItem(entry.storage_key)) {
                        updatedIndex.push(entry);
                    }
                });
            }
            
            localStorage.setItem('offline_scouting_index', JSON.stringify(updatedIndex));
            
            // Reset button state
            syncAllButton.disabled = false;
            syncAllButton.innerHTML = originalHtml;
            
            // Show result message
            showToast(`Sync complete: ${success} successful, ${failed} failed`, success > 0 ? 'success' : 'warning');
            
            // Refresh the list
            refreshOfflineEntries();
        }
    };
    
    // Initialize by refreshing the entries list
    refreshOfflineEntries();
    
    // Set up refresh button if it exists
    const refreshButton = document.getElementById('refresh-offline-data');
    if (refreshButton) {
        refreshButton.addEventListener('click', refreshOfflineEntries);
    }
}

// Initialize offline data manager when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    setupOfflineDataManager();
});

/**
 * Helper function to attempt recovery of malformed QR data
 * @param {string} rawData - The raw data from QR code
 * @returns {Object|null} - Recovered data object or null if recovery failed
 */
function attemptQRDataRecovery(rawData) {
    // Bail out early if empty data
    if (!rawData || rawData.trim() === '') return null;
    
    try {
        // First try direct JSON parse in case it's valid but threw an error in the main flow
        return JSON.parse(rawData);
    } catch (e) {
        // Continue with recovery methods
    }
    
    try {
        // Check if it's our minimal t/m/d format
        if (rawData.includes('"t":') && rawData.includes('"m":') && rawData.includes('"d":')) {
            // Try to fix common JSON formatting issues
            let fixedData = rawData.replace(/'/g, '"');  // Replace single quotes with double quotes
            fixedData = fixedData.replace(/(\w+):/g, '"$1":'); // Add quotes to keys
            
            // Try to parse again
            try {
                const parsed = JSON.parse(fixedData);
                
                // Expand to full format
                return {
                    team_id: parsed.t,
                    match_id: parsed.m,
                    data: parsed.d,
                    recovered: true
                };
            } catch (e) {
                // Continue with other methods
            }
        }
        
        // Check for comma-separated format
        if (rawData.includes(',') && !rawData.includes('{')) {
            const parts = rawData.split(',');
            if (parts.length >= 3) {
                // Assume team_id, match_id, data format
                return {
                    team_id: parts[0].trim(),
                    match_id: parts[1].trim(),
                    data: parts.slice(2).join(',').trim(),
                    recovered: true,
                    format: 'comma-separated'
                };
            }
        }
        
        // Check for colon-based format
        if (rawData.includes(':') && !rawData.includes('{')) {
            const parts = rawData.split(':');
            if (parts.length >= 2) {
                // Attempt to parse as key:value pairs
                const dataObj = {};
                
                for (let i = 0; i < parts.length; i += 2) {
                    if (i + 1 < parts.length) {
                        const key = parts[i].trim();
                        const value = parts[i + 1].trim();
                        dataObj[key] = isNaN(value) ? value : Number(value);
                    }
                }
                
                if (Object.keys(dataObj).length > 0) {
                    return {
                        recovered: true,
                        format: 'colon-separated',
                        ...dataObj
                    };
                }
            }
        }
        
        // Try to handle serialized or escaped JSON
        if (rawData.includes('\\')) {
            // Try to unescape
            const unescaped = rawData.replace(/\\"/g, '"')
                                      .replace(/\\\\/g, '\\')
                                      .replace(/\\n/g, '\n')
                                      .replace(/\\r/g, '\r')
                                      .replace(/\\t/g, '\t');
            
            // Check if it's now valid JSON
            try {
                return JSON.parse(unescaped);
            } catch (e) {
                // Continue with other methods
            }
        }
        
        // Last resort: If it looks like it has numbers and separators,
        // treat it as a key-value structure with = or : separators
        if (/[0-9]+[=:]/i.test(rawData)) {
            const dataObj = {};
            
            // Try to extract key-value pairs
            const pairs = rawData.match(/([A-Za-z0-9_]+)[=:]([^=:]+)(?=[A-Za-z0-9_]+[=:]|$)/g);
            
            if (pairs && pairs.length > 0) {
                pairs.forEach(pair => {
                    const [key, value] = pair.split(/[=:]/);
                    if (key && value) {
                        dataObj[key.trim()] = isNaN(value.trim()) ? value.trim() : Number(value.trim());
                    }
                });
                
                if (Object.keys(dataObj).length > 0) {
                    return {
                        recovered: true,
                        format: 'key-value-extracted',
                        ...dataObj
                    };
                }
            }
        }
        
        // If all attempts failed
        return null;
    } catch (error) {
        console.error('Recovery error:', error);
        return null;
    }
}

/**
 * Initialize scouting form with online/offline save functionality
 */
function initScoutingForm() {
    const form = document.getElementById('scouting-form');
    const saveButton = document.getElementById('save-button');
    const generateQRButton = document.getElementById('generateQR');
    
    if (!form || !saveButton) return;
    
    // Initialize points calculation
    initializePointsCalculation();
    
    // Handle save button click
    saveButton.addEventListener('click', function(e) {
        // Prevent default form submission
        e.preventDefault();
        
        // Check if we're online
        if (navigator.onLine) {
            // Online mode - submit the form directly
            submitScoutingForm();
        } else {
            // Offline mode - fall back to QR code generation
            showToast('You are currently offline. Generating QR code instead.', 'warning');
            generateQRCode();
        }
    });

    // Attach save-local handler via reusable function
    if (typeof setupSaveLocally === 'function') {
        try { setupSaveLocally(); } catch (e) { /* ignore */ }
    }
    
    // Submit the form data directly to the server
    function submitScoutingForm() {
        // Show loading state on button
        const originalText = saveButton.innerHTML;
        saveButton.disabled = true;
        saveButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Saving...';
        
        // Get form data
        const formData = new FormData(form);
        
        // Submit the form data
        fetch('/scouting/api/save', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            // Reset button state
            saveButton.disabled = false;
            saveButton.innerHTML = originalText;
            
            // Handle response
            if (data.success) {
                showToast('Scouting data saved successfully!', 'success');
                
                // Optional: Reset form or redirect
                if (data.redirect_url) {
                    setTimeout(() => {
                        window.location.href = data.redirect_url;
                    }, 1000);
                }
            } else {
                showToast(`Error: ${data.message || 'Failed to save data'}`, 'danger');
            }
        })
        .catch(error => {
            console.error('Error saving scouting data:', error);
            
            // Reset button state
            saveButton.disabled = false;
            saveButton.innerHTML = originalText;
            
            // Show error and fall back to QR code if it looks like a network issue
            showToast('Unable to save data directly. Falling back to QR code.', 'warning');
            setTimeout(() => {
                generateQRCode();
            }, 1000);
        });
    }
}

// Initialize the scouting form when the DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Add to the existing event listeners
    initScoutingForm();
});

/**
 * Attach handler to "Save Locally" button to persist form to localStorage
 */
function setupSaveLocally() {
    const form = document.getElementById('scouting-form');
    const saveLocalButton = document.getElementById('save-local-button');
    if (!form || !saveLocalButton) return;

    // Remove previous listener if present by cloning
    const newBtn = saveLocalButton.cloneNode(true);
    saveLocalButton.parentNode.replaceChild(newBtn, saveLocalButton);

    newBtn.addEventListener('click', function(e) {
        e.preventDefault();

        if (!form.checkValidity()) {
            form.classList.add('was-validated');
            showToast('Please fix form errors before saving locally', 'warning');
            return;
        }

        try {
            const formData = new FormData(form);
            const formObject = {};

            formData.forEach((value, key) => {
                const element = form.elements[key];
                if (element && element.type === 'checkbox') {
                    formObject[key] = element.checked;
                } else if (element && element.type === 'number' || (!isNaN(value) && value !== '')) {
                    formObject[key] = Number(value);
                } else {
                    formObject[key] = value;
                }
            });

            // Ensure unchecked checkboxes are included
            form.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
                if (!formObject.hasOwnProperty(checkbox.id)) {
                    formObject[checkbox.id] = false;
                }
            });

            // Add calculated points
            const pointsElements = document.querySelectorAll('.points-display');
            pointsElements.forEach(element => {
                const metricId = element.dataset.metricId;
                if (metricId) {
                    const pointsValue = element.querySelector('.points-value');
                    if (pointsValue) {
                        formObject[metricId + '_points'] = parseInt(pointsValue.textContent || '0');
                    }
                }
            });

            // Metadata
            formObject.generated_at = new Date().toISOString();
            formObject.offline_saved = true;

            // Defensive fallback: ensure scout_name is populated even if the input was left blank
            try {
                const scoutField = form.elements['scout_name'] || document.getElementById('scout_name');
                const fallbackScout = (scoutField && scoutField.placeholder) ? scoutField.placeholder : (scoutField && scoutField.value) ? scoutField.value : 'Unknown';
                if (!formObject.scout_name || (typeof formObject.scout_name === 'string' && formObject.scout_name.trim() === '')) {
                    formObject.scout_name = fallbackScout;
                }
            } catch (e) {
                // ignore any issues from missing elements
            }

            // Build storage key and index entry
            const timestamp = new Date().toISOString();
            const storageKey = `offline_scouting_${Date.now()}`;

            // Try to capture team/match numbers for the index
            const teamNumber = formObject.team_number || formObject.team_id || '';
            const matchNumber = formObject.match_number || formObject.match_id || '';

            // Save item
            localStorage.setItem(storageKey, JSON.stringify(formObject));

            // Update index
            let index = JSON.parse(localStorage.getItem('offline_scouting_index') || '[]');
            index.push({
                storage_key: storageKey,
                team_number: teamNumber,
                match_number: matchNumber,
                timestamp: timestamp
            });
            localStorage.setItem('offline_scouting_index', JSON.stringify(index));

            showToast('Form saved locally. You can sync it later from the Offline Data page.', 'success');

            // Refresh offline manager UI if present
            if (typeof setupOfflineDataManager === 'function') {
                try { setupOfflineDataManager(); } catch (e) { /* ignore */ }
            }
        } catch (error) {
            console.error('Error saving form locally:', error);
            showToast('Failed to save locally', 'danger');
        }
    });
}

function showDeleteConfirmNotification(btn, entryId) {
    // Use Bootstrap toast if available, else fallback to alert
    if (window.bootstrap && document.getElementById('delete-toast')) {
        const toast = document.getElementById('delete-toast');
        toast.querySelector('.toast-body').textContent = 'Click again to confirm delete.';
        new bootstrap.Toast(toast).show();
    } else {
        alert('Click again to confirm delete.');
    }
}

// Utility: Fetch API data from IndexedDB if offline
async function getAPIDataFromIDB(url) {
    return new Promise(resolve => {
        const open = indexedDB.open('ScoutAppDB', 1);
        open.onupgradeneeded = () => {
            open.result.createObjectStore('api', { keyPath: 'url' });
        };
        open.onsuccess = () => {
            const db = open.result;
            const tx = db.transaction('api', 'readonly');
            const req = tx.objectStore('api').get(url);
            req.onsuccess = () => {
                resolve(req.result ? req.result.data : null);
                db.close();
            };
            req.onerror = () => {
                resolve(null);
                db.close();
            };
        };
        open.onerror = () => resolve(null);
    });
}

// Example usage: Fetch API data, fallback to IndexedDB if offline
async function fetchWithOfflineFallback(apiUrl) {
    if (navigator.onLine) {
        try {
            const res = await fetch(apiUrl);
            if (res.ok) return await res.json();
        } catch (e) {
            // Network error, fallback to IDB
        }
    }
    // Offline or fetch failed
    const cached = await getAPIDataFromIDB(apiUrl);
    if (cached) return cached;
    throw new Error('No data available offline');
}