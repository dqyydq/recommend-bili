import { logout, setApiKey, setModel, getSettings } from "./api.js";
import { renderClassifyModule } from "./classify-module.js";
import { renderSearchModule } from "./search-module.js";
import { renderDustModule } from "./dust-module.js";
import { renderOrganizeModule } from "./organize-module.js";

export function renderConsole(app, user) {
  app.innerHTML = `
    <div class="console">
      <div class="sidebar">
        <div class="logo">收藏夹管家</div>
        <div class="menu-item active" data-page="classify">整理收藏夹</div>
        <div class="menu-item" data-page="search">寻找视频</div>
        <div class="menu-item" data-page="dust">吃灰检测</div>
        <div class="menu-item" data-page="organize">收藏夹整理</div>
      </div>
      <div class="main-area">
        <div class="header">
          <div class="page-title" id="pageTitle">整理收藏夹</div>
          <div class="user-info">
            <img src="${user.avatar || ''}" alt="" onerror="this.style.display='none'" />
            <span>${user.nickname || "用户"}</span>
            <button id="settingsBtn" class="logout-btn" title="设置" style="font-size:16px;">&#9881;</button>
            <button id="logoutBtn" class="logout-btn">退出</button>
          </div>
        </div>
        <div class="content" id="contentArea"></div>
      </div>
    </div>
  `;

  const pageTitle = document.getElementById("pageTitle");
  const contentArea = document.getElementById("contentArea");

  const pageMap = {
    classify: { title: "整理收藏夹", render: renderClassifyModule },
    search: { title: "寻找视频", render: renderSearchModule },
    dust: { title: "吃灰检测", render: renderDustModule },
    organize: { title: "收藏夹整理", render: renderOrganizeModule },
  };

  document.querySelectorAll(".menu-item").forEach(item => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".menu-item").forEach(i => i.classList.remove("active"));
      item.classList.add("active");
      const page = item.dataset.page;
      pageTitle.textContent = pageMap[page].title;
      pageMap[page].render(contentArea);
    });
  });

  document.getElementById("logoutBtn").addEventListener("click", async () => {
    try { await logout(); } catch (e) {}
    location.reload();
  });

  // 设置弹窗
  document.getElementById("settingsBtn").addEventListener("click", () => showSettingsModal());

  function showSettingsModal() {
    // Remove existing modal if any
    const existing = document.getElementById("settingsModal");
    if (existing) existing.remove();

    const modal = document.createElement("div");
    modal.id = "settingsModal";
    modal.className = "modal-overlay";
    modal.innerHTML = `
      <div class="modal">
        <h3>设置</h3>
        <div style="margin-bottom:14px;">
          <label style="display:block;font-size:13px;font-weight:600;color:#333;margin-bottom:4px;">DeepSeek API Key</label>
          <input id="settingsKeyInput" class="input" type="password" style="width:100%;" placeholder="sk-..." />
        </div>
        <div style="margin-bottom:14px;">
          <label style="display:block;font-size:13px;font-weight:600;color:#333;margin-bottom:4px;">模型</label>
          <input id="settingsModelInput" class="input" list="modelPresets" style="width:100%;" placeholder="deepseek-v4-flash" />
          <datalist id="modelPresets">
            <option value="deepseek-v4-flash">
            <option value="deepseek-chat">
            <option value="deepseek-reasoner">
          </datalist>
        </div>
        <p id="settingsError" style="color:#f43f5e;font-size:13px;display:none;"></p>
        <div class="modal-actions">
          <button id="cancelSettingsBtn" class="btn btn-secondary">取消</button>
          <button id="saveSettingsBtn" class="btn">保存</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    const keyInput = document.getElementById("settingsKeyInput");
    const modelInput = document.getElementById("settingsModelInput");

    // Load current settings
    getSettings().then(data => {
      keyInput.value = data.api_key || "";
      modelInput.value = data.model || "deepseek-v4-flash";
    }).catch(() => {});

    // Clear masked key on focus
    const currentKey = keyInput.value;
    keyInput.addEventListener("focus", () => {
      if (keyInput.value === currentKey && keyInput.value.includes("*")) {
        keyInput.value = "";
      }
    });

    document.getElementById("cancelSettingsBtn").addEventListener("click", () => modal.remove());
    document.getElementById("saveSettingsBtn").addEventListener("click", async () => {
      const newKey = keyInput.value.trim();
      const newModel = modelInput.value.trim() || "deepseek-v4-flash";
      const errEl = document.getElementById("settingsError");

      try {
        if (newKey && !newKey.includes("*")) {
          await setApiKey(newKey);
        }
        await setModel(newModel);
        modal.remove();
      } catch (e) {
        errEl.textContent = "保存失败: " + e.message;
        errEl.style.display = "block";
      }
    });

    // Close on overlay click
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.remove();
    });
  }

  // 默认加载整理收藏夹
  renderClassifyModule(contentArea);
}
