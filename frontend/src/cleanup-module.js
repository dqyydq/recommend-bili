import {
  createCleanupScan,
  executeCleanupScan,
  getCleanupScan,
  getLatestCleanupScan,
} from "./api.js";
import { escapeAttr, escapeHtml, formatError, showInlineMessage } from "./ui.js";

const VERDICT = {
  confirmed_invalid: "确定失效",
  review_required: "需要复核",
  unknown: "暂时未知",
  available: "当前可用",
};

export async function renderCleanupModule(container) {
  container.innerHTML = `
    <div class="destination-head compact"><div><span class="eyebrow">安全清理</span><h2>失效收藏扫描</h2><p>只会默认选择 B站明确返回不存在的视频，删除前还会再次验证。</p></div><button id="startCleanupScan" class="btn" type="button">开始扫描</button></div>
    <div id="cleanupStatus" class="task-status" hidden></div>
    <div id="cleanupResult"><p class="empty-state">还没有扫描记录。</p></div>`;
  const button = container.querySelector("#startCleanupScan");
  const status = container.querySelector("#cleanupStatus");
  const result = container.querySelector("#cleanupResult");
  try {
    const data = await getLatestCleanupScan();
    if (data.scan) renderScan(data.scan, result);
  } catch (error) {
    showInlineMessage(result, formatError(error, "扫描记录加载失败"));
  }
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.hidden = false;
    try {
      const data = await createCleanupScan();
      await pollScan(data.scan.id, status, result);
    } catch (error) {
      showInlineMessage(result, formatError(error, "扫描启动失败"));
    } finally {
      button.disabled = false;
    }
  });
}

async function pollScan(id, status, result) {
  for (;;) {
    const data = await getCleanupScan(id);
    const scan = data.scan;
    const percent = scan.total ? Math.round(Number(scan.checked || 0) / Number(scan.total) * 100) : 0;
    status.textContent = `${scan.message || "正在扫描"} · ${percent}%`;
    if (scan.status === "completed") {
      status.hidden = true;
      renderScan(scan, result);
      return;
    }
    if (scan.status === "failed") throw new Error(scan.error_message || "扫描失败");
    await new Promise(resolve => setTimeout(resolve, 900));
  }
}

function renderScan(scan, result) {
  const items = scan.items || [];
  result.innerHTML = `
    <div class="cleanup-counts">
      ${countCell("确定失效", scan.confirmed_invalid_count, "danger")}
      ${countCell("需要复核", scan.review_required_count, "warning")}
      ${countCell("暂时未知", scan.unknown_count, "muted")}
      ${countCell("当前可用", scan.available_count, "success")}
    </div>
    <div class="cleanup-actions"><span>仅“确定失效”会默认选中</span><button id="executeCleanup" class="btn" type="button">复核并移除所选项</button></div>
    <div class="cleanup-items">${items.map(item => renderItem(item)).join("") || `<p class="empty-state">扫描没有返回条目。</p>`}</div>`;
  const execute = result.querySelector("#executeCleanup");
  if (!execute) return;
  execute.disabled = !items.some(item => item.selected_by_default && item.execution_state === "pending");
  execute.addEventListener("click", async () => {
    const selected = [...result.querySelectorAll("[data-cleanup-item]:checked")].map(input => ({
      folder_id: Number(input.dataset.folderId), media_id: Number(input.dataset.mediaId),
    }));
    if (!selected.length) return;
    if (!window.confirm(`将再次验证并移除 ${selected.length} 条确定失效收藏，是否继续？`)) return;
    execute.disabled = true;
    try {
      const data = await executeCleanupScan(scan.id, selected);
      renderScan(data.scan, result);
    } catch (error) {
      showInlineMessage(result, formatError(error, "清理执行失败"));
    }
  });
}

function countCell(label, value, tone) {
  return `<div class="cleanup-count tone-${tone}"><strong>${Number(value || 0)}</strong><span>${escapeHtml(label)}</span></div>`;
}

function renderItem(item) {
  const pending = item.execution_state === "pending";
  return `<label class="cleanup-item verdict-${escapeAttr(item.verdict)}">
    <input data-cleanup-item data-folder-id="${Number(item.folder_id)}" data-media-id="${Number(item.media_id)}" type="checkbox" ${item.selected_by_default && pending ? "checked" : ""} ${item.verdict !== "confirmed_invalid" || !pending ? "disabled" : ""}>
    <span><strong>${escapeHtml(item.title || item.bvid || "未命名收藏")}</strong><small>${escapeHtml(VERDICT[item.verdict] || item.verdict)} · ${escapeHtml(item.reason || "")}</small>${!pending ? `<small>执行结果：${escapeHtml(item.execution_message || item.execution_state)}</small>` : ""}</span>
  </label>`;
}
