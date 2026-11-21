(function () {
    const header = document.querySelector('.site-header');
    const toggle = document.querySelector('[data-menu-toggle]');
    const navigation = document.getElementById('public-navigation');
    if (!header || !toggle || !navigation) return;

    const compact = window.matchMedia('(max-width: 1279px)');

    function measureHeader() {
        const position = window.getComputedStyle(header).position;
        const height = position === 'sticky' || position === 'fixed' ? header.getBoundingClientRect().height : 0;
        document.documentElement.style.setProperty('--header-height', `${Math.ceil(height)}px`);
    }

    function setMenu(open) {
        header.dataset.menuOpen = String(open);
        toggle.setAttribute('aria-expanded', String(open));
        measureHeader();
    }

    toggle.addEventListener('click', () => setMenu(header.dataset.menuOpen !== 'true'));
    header.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && compact.matches && header.dataset.menuOpen === 'true') {
            setMenu(false);
            toggle.focus();
        }
    });
    navigation.addEventListener('click', (event) => {
        if (compact.matches && event.target.closest('a')) setMenu(false);
    });
    if (compact.addEventListener) compact.addEventListener('change', () => setMenu(false));
    else compact.addListener(() => setMenu(false));
    window.addEventListener('resize', measureHeader);
    if ('ResizeObserver' in window) new ResizeObserver(measureHeader).observe(header);
    setMenu(false);

    const languageForm = document.querySelector('[data-public-language]');
    if (languageForm) {
        languageForm.querySelector('select').addEventListener('change', () => {
            languageForm.querySelector('[name="next"]').value = window.location.pathname + window.location.search + window.location.hash;
            if (languageForm.requestSubmit) languageForm.requestSubmit();
            else languageForm.submit();
        });
    }
    document.documentElement.classList.add('has-public-js');
    measureHeader();

    // Native anchors also work without JavaScript. Recheck the initial fragment
    // after the real (possibly wrapped) sticky header has been measured.
    function alignInitialFragment() {
        measureHeader();
        const target = document.getElementById(window.location.hash.slice(1));
        if (target) target.scrollIntoView({block: 'start', behavior: 'auto'});
    }
    window.addEventListener('pageshow', () => window.requestAnimationFrame(alignInitialFragment));
}());

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
            dot.setAttribute('aria-pressed', isActive ? 'true' : 'false');
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
            resumeTimeoutId = window.setTimeout(() => {
                if (!carousel.contains(document.activeElement) && !carousel.matches(':hover')) startAutoplay();
            }, resumeDelayMs);
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
    carousel.addEventListener('mouseleave', () => {
        if (!carousel.contains(document.activeElement)) startAutoplay();
    });
    carousel.addEventListener('focusin', stopAutoplay);
    carousel.addEventListener('focusout', (event) => {
        if (!carousel.contains(event.relatedTarget)) startAutoplay();
    });

    setSlide(0);
    startAutoplay();
}());

(function () {
    const carousels = Array.from(document.querySelectorAll('[data-people-carousel]'));
    if (!carousels.length) return;

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const peopleIntervalMs = 5000;

    carousels.forEach((carousel) => {
        const slides = Array.from(carousel.querySelectorAll('[data-people-slide]'));
        if (!slides.length) return;

        let currentIndex = 0;
        let intervalId = null;

        function setSlide(index) {
            currentIndex = (index + slides.length) % slides.length;
            slides.forEach((slide, slideIndex) => {
                const isActive = slideIndex === currentIndex;
                slide.classList.toggle('is-active', isActive);
                slide.setAttribute('aria-hidden', isActive ? 'false' : 'true');
            });
        }

        function startAutoplay() {
            if (prefersReducedMotion || slides.length <= 1 || intervalId) return;
            intervalId = window.setInterval(() => setSlide(currentIndex + 1), peopleIntervalMs);
        }

        setSlide(0);
        startAutoplay();
    });
}());

(function () {
    const section = document.querySelector('[data-pricing-section]');
    if (!section) return;

    const toggle = section.querySelector('[data-pricing-toggle]');
    if (!toggle) return;

    const buttons = Array.from(toggle.querySelectorAll('[data-pricing-cycle]'));
    const prices = Array.from(section.querySelectorAll('[data-cycle-price]'));
    const notes = Array.from(section.querySelectorAll('[data-cycle-note]'));
    const ctas = Array.from(section.querySelectorAll('[data-pricing-cta]'));

    function setBillingCycle(cycle) {
        section.dataset.billingCycle = cycle;
        buttons.forEach((button) => {
            const isActive = button.dataset.pricingCycle === cycle;
            button.classList.toggle('is-active', isActive);
            button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
        prices.forEach((price) => {
            price.hidden = price.dataset.cyclePrice !== cycle;
        });
        notes.forEach((note) => {
            note.hidden = note.dataset.cycleNote !== cycle;
        });
        ctas.forEach((cta) => {
            const nextUrl = cycle === 'yearly' ? cta.dataset.signupYearlyUrl : cta.dataset.signupMonthlyUrl;
            if (nextUrl) cta.setAttribute('href', nextUrl);
        });
    }

    buttons.forEach((button) => {
        button.addEventListener('click', () => setBillingCycle(button.dataset.pricingCycle));
    });

    setBillingCycle('monthly');
}());
