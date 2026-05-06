export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#96;");
}

export function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2600);
}

export function showInlineMessage(el, message, type = "error") {
  const color = type === "success" ? "#22c55e" : type === "muted" ? "#999" : "#f43f5e";
  el.innerHTML = `<p style="color:${color};">${escapeHtml(message)}</p>`;
}

export function setButtonBusy(button, busy, busyText = "处理中…") {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.disabled = true;
    button.textContent = busyText;
  } else {
    button.disabled = false;
    if (button.dataset.originalText) {
      button.textContent = button.dataset.originalText;
      delete button.dataset.originalText;
    }
  }
}

export function formatError(error, fallback = "操作失败") {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  return error.message || fallback;
}
