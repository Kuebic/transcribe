// Upload progress. The form is sent with XMLHttpRequest instead of a plain submit so a large upload
// (a 2 h lecture) shows how far it has got. The server's answer is then shown as if the form had
// been submitted normally: a redirect opens that page, anything else replaces this one.
(() => {
  const form = document.querySelector("form.upload");
  if (!form) return;
  const button = form.querySelector('button[type="submit"]');
  const panel = form.querySelector(".upload-progress");
  const bar = panel.querySelector("progress");
  const status = panel.querySelector(".upload-status");

  function megabytes(bytes) {
    return (bytes / 1024 ** 2).toFixed(1);
  }

  function fail(message) {
    status.textContent = message;
    button.disabled = false;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const files = [...form.querySelector('input[type="file"]').files];
    const names = files.map((file) => file.name).join(", ");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);

    xhr.upload.addEventListener("progress", (progress) => {
      if (!progress.lengthComputable) return;
      bar.value = (100 * progress.loaded) / progress.total;
      status.textContent =
        `Uploading ${names}: ${megabytes(progress.loaded)} of ${megabytes(progress.total)} MB`;
    });
    xhr.upload.addEventListener("load", () => {
      bar.removeAttribute("value");
      status.textContent = `Uploaded ${names}; storing…`;
    });

    xhr.addEventListener("load", () => {
      if (xhr.responseURL && new URL(xhr.responseURL).pathname !== new URL(form.action).pathname) {
        window.location.assign(xhr.responseURL);
        return;
      }
      document.open();
      document.write(xhr.responseText);
      document.close();
    });
    xhr.addEventListener("error", () => fail("Upload failed: the connection was lost or the files are too large."));
    xhr.addEventListener("abort", () => fail("Upload cancelled."));

    button.disabled = true;
    bar.value = 0;
    status.textContent = `Uploading ${names}…`;
    panel.hidden = false;
    xhr.send(new FormData(form));
  });
})();
