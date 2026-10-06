// Copy buttons. Each fetches its transcript text when the page loads, so the click can write the
// clipboard while the browser still counts it as a user gesture. A plain-HTTP LAN page is not a
// secure context and has no navigator.clipboard, so copying falls back to a hidden textarea.
(() => {
  const CONFIRM_MS = 2000;

  function copyWithTextarea(text) {
    const area = document.createElement("textarea");
    area.value = text;
    area.readOnly = true;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    area.setSelectionRange(0, text.length);
    try {
      return document.execCommand("copy");
    } finally {
      area.remove();
    }
  }

  async function copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else if (!copyWithTextarea(text)) {
      throw new Error("The browser refused to copy");
    }
  }

  function confirm(button, message, className) {
    button.textContent = message;
    button.classList.remove("copied", "copy-failed");
    button.classList.add(className);
    clearTimeout(button.resetTimer);
    button.resetTimer = setTimeout(() => {
      button.textContent = button.dataset.label;
      button.classList.remove(className);
    }, CONFIRM_MS);
  }

  for (const button of document.querySelectorAll("button.copy")) {
    button.dataset.label = button.textContent;
    let text = null;
    let loading = null;
    const load = () => {
      loading ??= fetch(button.dataset.src)
        .then((response) => {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return response.text();
        })
        .then(
          (body) => (text = body),
          (error) => {
            loading = null;
            throw error;
          },
        );
      return loading;
    };
    load().catch(() => {});

    button.addEventListener("click", async () => {
      try {
        await copy(text ?? (await load()));
        confirm(button, "Copied ✓", "copied");
      } catch {
        confirm(button, "Copy failed", "copy-failed");
      }
    });
  }
})();
