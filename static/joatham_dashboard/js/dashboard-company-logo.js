/* The adjacent company name supplies the accessible identity. */
document.querySelectorAll("[data-company-logo]").forEach((image) => {
    const showInitial = () => { image.hidden = true; };
    image.addEventListener("error", showInitial, {once: true});
    if (image.complete && image.naturalWidth === 0) {
        showInitial();
    }
});
