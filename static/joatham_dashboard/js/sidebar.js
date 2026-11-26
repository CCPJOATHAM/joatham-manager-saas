(() => {
    const sidebar = document.querySelector(".jm-sidebar");
    if (!sidebar) return;
    const button = sidebar.querySelector(".jm-menu-toggle");
    const panel = sidebar.querySelector(".jm-sidebar-panel");
    const mobile = window.matchMedia("(max-width: 1120px)");
    const setOpen = (open) => {
        panel.hidden = !open;
        button.setAttribute("aria-expanded", String(open));
    };
    const adapt = () => {
        button.hidden = !mobile.matches;
        setOpen(!mobile.matches);
    };
    button.addEventListener("click", () => setOpen(panel.hidden));
    sidebar.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && mobile.matches && !panel.hidden) {
            setOpen(false);
            button.focus();
        }
    });
    mobile.addEventListener("change", adapt);
    adapt();
})();
