(function () {
    const carousel = document.querySelector('[data-product-carousel]');
    if (!carousel) return;

    const slides = Array.from(carousel.querySelectorAll('[data-carousel-slide]'));
    const dots = Array.from(carousel.querySelectorAll('[data-carousel-dot]'));
    const previousButton = carousel.querySelector('[data-carousel-prev]');
    const nextButton = carousel.querySelector('[data-carousel-next]');
    const title = carousel.querySelector('[data-carousel-title]');
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const intervalMs = 5000;
    const resumeDelayMs = 9000;
    let currentIndex = 0;
    let intervalId = null;
    let resumeTimeoutId = null;

    function setSlide(index) {
        currentIndex = (index + slides.length) % slides.length;
        slides.forEach((slide, slideIndex) => {
            const isActive = slideIndex === currentIndex;
            slide.classList.toggle('is-active', isActive);
            slide.setAttribute('aria-hidden', isActive ? 'false' : 'true');
        });
        dots.forEach((dot, dotIndex) => {
            const isActive = dotIndex === currentIndex;
            dot.classList.toggle('is-active', isActive);
            dot.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        if (title) {
            title.textContent = slides[currentIndex].querySelector('figcaption').textContent;
        }
    }

    function stopAutoplay() {
        if (intervalId) {
            window.clearInterval(intervalId);
            intervalId = null;
        }
    }

    function startAutoplay() {
        if (prefersReducedMotion || intervalId) return;
        intervalId = window.setInterval(() => setSlide(currentIndex + 1), intervalMs);
    }

    function pauseAfterInteraction() {
        stopAutoplay();
        if (resumeTimeoutId) window.clearTimeout(resumeTimeoutId);
        if (!prefersReducedMotion) {
            resumeTimeoutId = window.setTimeout(startAutoplay, resumeDelayMs);
        }
    }

    previousButton.addEventListener('click', () => {
        setSlide(currentIndex - 1);
        pauseAfterInteraction();
    });

    nextButton.addEventListener('click', () => {
        setSlide(currentIndex + 1);
        pauseAfterInteraction();
    });

    dots.forEach((dot, index) => {
        dot.addEventListener('click', () => {
            setSlide(index);
            pauseAfterInteraction();
        });
    });

    carousel.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            setSlide(currentIndex - 1);
            pauseAfterInteraction();
        }
        if (event.key === 'ArrowRight') {
            event.preventDefault();
            setSlide(currentIndex + 1);
            pauseAfterInteraction();
        }
        if (event.key === 'Home') {
            event.preventDefault();
            setSlide(0);
            pauseAfterInteraction();
        }
        if (event.key === 'End') {
            event.preventDefault();
            setSlide(slides.length - 1);
            pauseAfterInteraction();
        }
    });

    carousel.addEventListener('mouseenter', stopAutoplay);
    carousel.addEventListener('mouseleave', startAutoplay);
    carousel.addEventListener('focusin', stopAutoplay);
    carousel.addEventListener('focusout', startAutoplay);

    setSlide(0);
    startAutoplay();
}());