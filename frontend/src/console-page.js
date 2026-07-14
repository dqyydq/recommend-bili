import { clearAgentMemories, exportUserData, getSettings, getSyncStatus, logout, setApiKey, setModel, startSync } from "./api.js";
import { renderLearningProjectsAgent } from "./agents-module.js";
import { renderCollectionLibrary } from "./collection-library.js";
import { renderOperationsModule } from "./operations-module.js";
import { renderWorkspaceModule } from "./workspace-module.js";
import { renderProfileModule } from "./profile-module.js";
import { escapeAttr, escapeHtml, setButtonBusy, showToast } from "./ui.js";

export function renderConsole(app, user) {
  app.innerHTML = `
    <div class="app-shell">
      <header class="app-header">
        <button class="brand" data-page="workspace" type="button" aria-label="返回工作台">
          <span class="brand-mark">F</span><span>收藏夹管家</span>
        </button>
        <nav class="primary-nav" aria-label="主导航">
          <button class="active" data-page="workspace" type="button">工作台</button>
          <button data-page="library" type="button">收藏库</button>
          <button data-page="learning" type="button">学习项目</button>
          <button data-page="profile" type="button">我的画像</button>
          <button data-page="operations" type="button">操作记录</button>
        </nav>
        <div class="header-actions">
          <button id="syncBtn" class="header-button" type="button"><span class="sync-dot"></span><span id="syncLabel">同步</span></button>
          <button id="settingsBtn" class="header-button" type="button">设置</button>
          <div class="user-menu">
            ${user.avatar ? `<img src="${escapeAttr(user.avatar)}" alt="" onerror="this.style.display='none'" />` : ""}
            <span>${escapeHtml(user.nickname || "用户")}</span>
            <button id="logoutBtn" type="button">退出</button>
          </div>
        </div>
      </header>
      <main class="app-content" id="contentArea"></main>
    </div>`;

  const content = document.getElementById("contentArea");
  const pages = {
    workspace: () => renderWorkspaceModule(content, { navigate }),
    library: () => renderCollectionLibrary(content),
    learning: () => renderLearningProjectsAgent(content),
    profile: () => renderProfileModule(content),
    operations: () => renderOperationsModule(content),
  };

  function navigate(page) {
    const destination = pages[page] ? page : "workspace";
    document.querySelectorAll("[data-page]").forEach(button => button.classList.toggle("active", button.dataset.page === destination));
    content.setAttribute("data-view", destination);
    pages[destination]();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.querySelectorAll("[data-page]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.page)));
  document.getElementById("logoutBtn").addEventListener("click", async () => {
    try { await logout(); } catch (_) { /* Reload still clears stale client state. */ }
    location.reload();
  });

  bindSync();
  document.getElementById("settingsBtn").addEventListener("click", showSettingsModal);
  navigate("workspace");
  if (!user.has_key) setTimeout(showSettingsModal, 500);
}

function bindSync() {
  const button = document.getElementById("syncBtn");
  const label = document.getElementById("syncLabel");
  async function refresh() {
    try {
      const data = await getSyncStatus();
      const job = data.job;
      if (!job) { label.textContent = "尚未同步"; return; }
      if (["queued", "running"].includes(job.status)) {
        button.disabled = true;
        label.textContent = `${Number(job.folders_processed || 0)}/${Number(job.folders_total || 0)}`;
        setTimeout(refresh, 1500);
        return;
      }
      button.disabled = false;
      label.textContent = job.status === "completed" ? "已同步" : "同步失败";
      button.classList.toggle("has-error", job.status === "failed");
    } catch (_) { label.textContent = "状态不可用"; }
  }
  button.addEventListener("click", async () => {
    try {
      button.disabled = true;
      label.textContent = "同步中…";
      await startSync(false);
      refresh();
    } catch (error) {
      showToast(`同步失败：${error.message}`, "error");
      button.disabled = false;
      label.textContent = "重试同步";
    }
  });
  refresh();
}

function showSettingsModal() {
  document.getElementById("settingsModal")?.remove();
  const modal = document.createElement("div");
  modal.id = "settingsModal";
  modal.className = "modal-overlay";
  modal.tabIndex = -1;
  modal.innerHTML = `
    <div class="modal settings-modal" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
      <div class="modal-heading"><div><span class="eyebrow">模型连接</span><h2 id="settingsTitle">设置</h2></div><button id="closeSettingsBtn" class="icon-button" type="button" aria-label="关闭">×</button></div>
      <label class="form-field"><span>模型 API Key</span><input id="settingsKeyInput" class="input" type="password" autocomplete="off" placeholder="sk-..." /></label>
      <label class="form-field"><span>OpenAI-compatible Base URL</span><input id="settingsBaseUrlInput" class="input" placeholder="https://api.deepseek.com" /></label>
      <label class="form-field"><span>模型</span><input id="settingsModelInput" class="input" list="modelPresets" placeholder="deepseek-v4-flash" /></label>
      <datalist id="modelPresets"><option value="deepseek-v4-flash"><option value="deepseek-chat"><option value="deepseek-reasoner"></datalist>
      <p id="settingsError" class="inline-error" hidden></p>
      <div class="settings-data-actions"><button id="exportDataButton" class="text-button" type="button">导出我的数据</button><button id="clearMemoriesButton" class="text-button danger-text" type="button">清空 Agent 记忆</button></div>
      <div class="modal-actions"><button id="cancelSettingsBtn" class="btn btn-secondary" type="button">取消</button><button id="saveSettingsBtn" class="btn" type="button">保存</button></div>
    </div>`;
  document.body.appendChild(modal);
  modal.focus();

  const keyInput = document.getElementById("settingsKeyInput");
  const modelInput = document.getElementById("settingsModelInput");
  const baseUrlInput = document.getElementById("settingsBaseUrlInput");
  let maskedKey = "";
  getSettings().then(data => {
    maskedKey = data.api_key || "";
    keyInput.value = maskedKey;
    modelInput.value = data.model || "deepseek-v4-flash";
    baseUrlInput.value = data.base_url || "https://api.deepseek.com";
  }).catch(() => {});
  keyInput.addEventListener("focus", () => { if (maskedKey && keyInput.value === maskedKey && maskedKey.includes("*")) keyInput.value = ""; });

  const close = () => modal.remove();
  document.getElementById("closeSettingsBtn").addEventListener("click", close);
  document.getElementById("cancelSettingsBtn").addEventListener("click", close);
  modal.addEventListener("click", event => { if (event.target === modal) close(); });
  modal.addEventListener("keydown", event => { if (event.key === "Escape") close(); });
  document.getElementById("saveSettingsBtn").addEventListener("click", async event => {
    const saveButton = event.currentTarget;
    const errorElement = document.getElementById("settingsError");
    try {
      errorElement.hidden = true;
      setButtonBusy(saveButton, true, "保存中…");
      const key = keyInput.value.trim();
      if (key && !key.includes("*")) await setApiKey(key);
      await setModel(modelInput.value.trim() || "deepseek-v4-flash", baseUrlInput.value.trim() || "https://api.deepseek.com");
      close();
      showToast("设置已保存", "success");
    } catch (error) {
      errorElement.textContent = `保存失败：${error.message}`;
      errorElement.hidden = false;
    } finally { setButtonBusy(saveButton, false); }
  });
  document.getElementById("exportDataButton").addEventListener("click", async () => {
    try {
      const data = await exportUserData();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      link.download = `favorite-agent-export-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (error) { showToast(`导出失败：${error.message}`, "error"); }
  });
  document.getElementById("clearMemoriesButton").addEventListener("click", async () => {
    const confirmation = window.prompt("输入 CLEAR MEMORIES 清空长期记忆。收藏数据不会删除。") || "";
    if (!confirmation) return;
    try { const data = await clearAgentMemories(confirmation); showToast(`已清空 ${Number(data.cleared || 0)} 条记忆`, "success"); }
    catch (error) { showToast(`清空失败：${error.message}`, "error"); }
  });
}
