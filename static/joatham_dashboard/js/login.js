const passwordInput = document.getElementById("id_password");
const togglePasswordButton = document.getElementById("togglePassword");

togglePasswordButton.hidden = false;
togglePasswordButton.addEventListener("click", () => {
    const showPassword = passwordInput.type === "password";
    passwordInput.type = showPassword ? "text" : "password";
    togglePasswordButton.setAttribute("aria-pressed", String(showPassword));
});
