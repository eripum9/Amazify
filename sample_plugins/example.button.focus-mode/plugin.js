let enabled = false;

const button = Amazify.ui.addHeaderAction(manifest.id, "F", () => {
  enabled = !enabled;
  document.body.classList.toggle("amazify-focus-mode", enabled);
  button.setAttribute("aria-pressed", String(enabled));
});

button.title = "Focus mode";
button.setAttribute("aria-label", "Toggle focus mode");
button.setAttribute("aria-pressed", "false");

return () => {
  document.body.classList.remove("amazify-focus-mode");
};
