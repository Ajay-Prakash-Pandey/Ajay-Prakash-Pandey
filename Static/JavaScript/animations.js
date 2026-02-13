/* ===================================
   PORTFOLIO ANIMATION HANDLER
   Advanced scroll and interaction animations
   =================================== */

// Intersection Observer for scroll animations
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('animate-in');
            // Optional: stop observing after animation
            // observer.unobserve(entry.target);
        }
    });
}, observerOptions);

// Observe all elements with animation classes
document.addEventListener('DOMContentLoaded', () => {
    // Animate cards on scroll
    const cards = document.querySelectorAll('.card-professional, .service-card, .project-card, .skill-card');
    cards.forEach(card => {
        card.classList.add('animate-in-on-scroll');
        observer.observe(card);
    });

    // Animate section headings
    const headings = document.querySelectorAll('.section-heading, h2, h3');
    headings.forEach(heading => {
        heading.classList.add('heading-animate');
        observer.observe(heading);
    });

    // Animate paragraphs
    const paragraphs = document.querySelectorAll('p, .text-professional');
    paragraphs.forEach(para => {
        para.classList.add('text-animate');
        observer.observe(para);
    });

    // Counter animation for statistics
    animateCounters();

    // Smooth scroll for navigation links
    setupSmoothScroll();

    // Add hover effects to interactive elements
    setupInteractiveEffects();

    // Parallax scroll effect
    setupParallax();
});

// Animated counters for statistics
function animateCounters() {
    const counters = document.querySelectorAll('[data-count]');
    
    counters.forEach(counter => {
        const target = parseInt(counter.getAttribute('data-count'));
        const duration = 2000; // 2 seconds
        const increment = target / (duration / 16);
        let current = 0;

        const updateCounter = () => {
            current += increment;
            if (current < target) {
                counter.textContent = Math.floor(current);
                requestAnimationFrame(updateCounter);
            } else {
                counter.textContent = target;
            }
        };

        // Start animation when element is in view
        observer.observe(counter.parentElement);
        counter.parentElement.addEventListener('animatein', updateCounter, { once: true });
    });
}

// Smooth scroll for anchor links
function setupSmoothScroll() {
    const links = document.querySelectorAll('a[href^="#"]');
    
    links.forEach(link => {
        link.addEventListener('click', (e) => {
            const href = link.getAttribute('href');
            if (href !== '#' && document.querySelector(href)) {
                e.preventDefault();
                const element = document.querySelector(href);
                element.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

// Interactive effects
function setupInteractiveEffects() {
    // Button ripple effect
    const buttons = document.querySelectorAll('.btn-professional, .btn, button');
    
    buttons.forEach(button => {
        button.addEventListener('click', (e) => {
            const ripple = document.createElement('span');
            const rect = button.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;
            
            ripple.style.width = ripple.style.height = size + 'px';
            ripple.style.left = x + 'px';
            ripple.style.top = y + 'px';
            ripple.classList.add('ripple');
            
            button.appendChild(ripple);
            
            setTimeout(() => ripple.remove(), 600);
        });
    });

    // Card hover lift effect
    const cards = document.querySelectorAll('.card-professional, .service-card, .project-card');
    
    cards.forEach(card => {
        card.addEventListener('mousemove', (e) => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;
            
            const angleX = (y - centerY) / 10;
            const angleY = (centerX - x) / 10;
            
            card.style.transform = `perspective(1000px) rotateX(${angleX}deg) rotateY(${angleY}deg) scale(1.02)`;
        });
        
        card.addEventListener('mouseleave', () => {
            card.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) scale(1)';
        });
    });
}

// Parallax scroll effect
function setupParallax() {
    const parallaxElements = document.querySelectorAll('.parallax');
    
    if (parallaxElements.length === 0) return;
    
    window.addEventListener('scroll', () => {
        parallaxElements.forEach(element => {
            const rect = element.getBoundingClientRect();
            const speed = 0.5;
            element.style.backgroundPosition = `center ${window.scrollY * speed}px`;
        });
    });
}

// Add ripple effect styling
const style = document.createElement('style');
style.textContent = `
    .ripple {
        position: absolute;
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.6);
        transform: scale(0);
        animation: ripple-animation 0.6s ease-out;
        pointer-events: none;
    }

    @keyframes ripple-animation {
        to {
            transform: scale(4);
            opacity: 0;
        }
    }

    /* Scroll animation classes */
    .animate-in-on-scroll {
        opacity: 0;
        animation: none;
    }

    .animate-in {
        animation: cardSlideUp 0.6s ease-out forwards;
    }

    .heading-animate {
        opacity: 0;
    }

    .heading-animate.animate-in {
        animation: headingSlide 0.7s ease-out forwards;
    }

    .text-animate {
        opacity: 0;
    }

    .text-animate.animate-in {
        animation: textReveal 0.8s ease-out forwards;
    }

    /* 3D card effect smooth transition */
    .card-professional {
        transition: transform 0.3s cubic-bezier(0.23, 1, 0.320, 1);
    }

    /* Gradient animated background */
    .gradient-bg-animate {
        background: linear-gradient(-45deg, #1a365d, #b8860b, #2c5282, #1a365d);
        background-size: 400% 400%;
        animation: gradientShift 15s ease infinite;
    }

    @keyframes gradientShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
`;
document.head.appendChild(style);

// Expose animation trigger for dynamic content
window.triggerAnimation = (element) => {
    if (element) {
        element.classList.add('animate-in');
    }
};

// Scroll reveal animation
window.addEventListener('scroll', () => {
    const elements = document.querySelectorAll('.animate-in-on-scroll:not(.animate-in)');
    
    elements.forEach(element => {
        const rect = element.getBoundingClientRect();
        const isVisible = rect.top < window.innerHeight && rect.bottom > 0;
        
        if (isVisible) {
            element.classList.add('animate-in');
        }
    });
});

// Page transition animations
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPageAnimations);
} else {
    initPageAnimations();
}

function initPageAnimations() {
    // Fade in on page load
    document.body.style.opacity = '0';
    document.body.offsetHeight; // Trigger reflow
    document.body.style.transition = 'opacity 0.8s ease-out';
    document.body.style.opacity = '1';
}

// Intersection observer for counting elements
const countObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting && entry.target.getAttribute('data-count')) {
            const counter = entry.target;
            const target = parseInt(counter.getAttribute('data-count'));
            const duration = 1500;
            const start = Date.now();
            
            const animate = () => {
                const now = Date.now();
                const progress = Math.min((now - start) / duration, 1);
                counter.textContent = Math.floor(progress * target);
                
                if (progress < 1) {
                    requestAnimationFrame(animate);
                } else {
                    counter.textContent = target;
                }
            };
            
            animate();
            countObserver.unobserve(entry.target);
        }
    });
}, { threshold: 0.1 });

// Observe all count elements
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-count]').forEach(el => {
        countObserver.observe(el);
    });
});

// Page visibility animation
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        document.body.style.opacity = '0.95';
        setTimeout(() => {
            document.body.style.opacity = '1';
        }, 100);
    }
});
