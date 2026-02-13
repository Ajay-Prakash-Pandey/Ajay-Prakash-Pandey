/**
 * Dashboard Interactive Features
 * Smooth interactions for skills and projects management
 */

document.addEventListener('DOMContentLoaded', function() {
    initDashboard();
});

function initDashboard() {
    // Proficiency range slider
    initProficiencySlider();
    
    // Smooth animations
    addElementAnimations();
    
    // Form validation
    initFormValidation();
}

/**
 * Update proficiency value display in real-time
 */
function initProficiencySlider() {
    const slider = document.getElementById('proficiency');
    const valueDisplay = document.getElementById('proficiency-value');
    
    if (slider && valueDisplay) {
        slider.addEventListener('input', function() {
            valueDisplay.textContent = this.value + '%';
            
            // Visual feedback
            const percentage = (this.value - this.min) / (this.max - this.min) * 100;
            this.style.background = `linear-gradient(to right, #007bff 0%, #007bff ${percentage}%, #e0e0e0 ${percentage}%, #e0e0e0 100%)`;
        });
        
        // Set initial background
        slider.style.background = `linear-gradient(to right, #007bff 0%, #007bff 50%, #e0e0e0 50%, #e0e0e0 100%)`;
    }
}

/**
 * Add smooth scroll animations to elements
 */
function addElementAnimations() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.1
    });

    // Observe all dashboard sections
    document.querySelectorAll('.dashboard-section, .skill-item, table tr').forEach(element => {
        element.style.opacity = '0';
        element.style.transform = 'translateY(20px)';
        element.style.transition = 'all 0.4s ease-out';
        observer.observe(element);
    });
}

/**
 * Form validation for skill and project forms
 */
function initFormValidation() {
    const forms = document.querySelectorAll('form');
    
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const inputs = this.querySelectorAll('input[required], textarea[required], select[required]');
            let isValid = true;
            
            inputs.forEach(input => {
                if (!input.value.trim()) {
                    isValid = false;
                    highlightError(input);
                } else {
                    clearError(input);
                }
            });
            
            if (!isValid) {
                e.preventDefault();
                showNotification('Please fill in all required fields', 'error');
            }
        });
    });
}

/**
 * Highlight invalid form field
 */
function highlightError(element) {
    element.style.borderColor = '#dc3545';
    element.style.boxShadow = '0 0 0 3px rgba(220, 53, 69, 0.1)';
}

/**
 * Clear error highlight from form field
 */
function clearError(element) {
    element.style.borderColor = '#dee2e6';
    element.style.boxShadow = 'none';
}

/**
 * Show notification message
 */
function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'success' ? '#28a745' : '#dc3545'};
        color: white;
        padding: 12px 20px;
        border-radius: 6px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        font-weight: 600;
        z-index: 10000;
        animation: slideInRight 0.3s ease-out;
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOutRight 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

/**
 * Add delete confirmation
 */
function confirmDelete(event, itemName = 'this item') {
    const confirmed = confirm(`Are you sure you want to delete ${itemName}? This action cannot be undone.`);
    if (!confirmed) {
        event.preventDefault();
    }
}

/**
 * Toggle form display
 */
function toggleForm(formId) {
    const form = document.getElementById(formId);
    if (form) {
        form.style.display = form.style.display === 'none' ? 'block' : 'none';
    }
}

/**
 * Add keyboard shortcuts
 */
document.addEventListener('keydown', function(e) {
    // ESC to close dialogs
    if (e.key === 'Escape') {
        document.querySelectorAll('[role="dialog"]').forEach(dialog => {
            dialog.style.display = 'none';
        });
    }
    
    // Ctrl/Cmd + Enter to submit focused form
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        const form = document.querySelector('form:focus-within');
        if (form && form.querySelector('button[type="submit"]')) {
            form.querySelector('button[type="submit"]').click();
        }
    }
});

/**
 * CSS animations (to be added to stylesheet)
 */
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            opacity: 0;
            transform: translateX(100px);
        }
        to {
            opacity: 1;
            transform: translateX(0);
        }
    }
    
    @keyframes slideOutRight {
        from {
            opacity: 1;
            transform: translateX(0);
        }
        to {
            opacity: 0;
            transform: translateX(100px);
        }
    }
    
    @keyframes pulse {
        0%, 100% {
            opacity: 1;
        }
        50% {
            opacity: 0.5;
        }
    }
    
    .loading {
        animation: pulse 1.5s ease-in-out infinite;
    }
`;
document.head.appendChild(style);

// Export functions for inline use
window.dashboardUtils = {
    confirmDelete,
    toggleForm,
    showNotification
};

// Legacy function support
function showAlert(section) {
  alert(`You clicked on the "${section}" card!`);
}
