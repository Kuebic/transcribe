// Theme toggle. Every page view starts on the system light/dark setting; the toggle overrides it
// for that view only, so the next page load follows the system again. Nothing is stored.
(() => {
  const button = document.querySelector("button.theme-toggle");
  if (!button) return;

  const root = document.documentElement;
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  let override = null;

  function isDark() {
    return override ? override === "dark" : systemDark.matches;
  }

  function render() {
    root.style.colorScheme = override ?? "";
    button.textContent = isDark() ? "Light mode" : "Dark mode";
  }

  button.addEventListener("click", () => {
    override = isDark() ? "light" : "dark";
    render();
  });
  systemDark.addEventListener("change", render);

  button.hidden = false;
  render();
})();
