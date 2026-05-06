import { searchFavorites, searchAll, addToFavorite, getFolders } from "./api.js";
import { escapeAttr, escapeHtml, formatError, setButtonBusy, showInlineMessage, showToast } from "./ui.js";

let cachedFolders = [];

export async function renderSearchModule(container) {
  container.innerHTML = `
    <div>
      <div class="tabs">
        <div class="tab active" data-tab="in-fav">搜索已收藏</div>
        <div class="tab" data-tab="all">搜索全站</div>
      </div>
      <div class="search-bar">
        <input id="searchInput" class="input" placeholder="输入关键词搜索…" style="flex:1;" />
        <button id="searchBtn" class="btn">搜索</button>
        <span id="searchSpinner" style="display:none;" class="spinner"></span>
      </div>
      <div id="searchResult"></div>
      <div id="addModal" style="display:none;"></div>
    </div>
  `;

  try {
    const data = await getFolders();
    cachedFolders = data.folders || [];
  } catch (e) {}

  let currentTab = "in-fav";

  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentTab = tab.dataset.tab;
      document.getElementById("searchInput").value = "";
      document.getElementById("searchResult").innerHTML = "";
    });
  });

  document.getElementById("searchBtn").addEventListener("click", async () => {
    const q = document.getElementById("searchInput").value.trim();
    if (!q) return;
    const resultEl = document.getElementById("searchResult");
    const spinner = document.getElementById("searchSpinner");
    spinner.style.display = "inline-block";
    resultEl.innerHTML = "";
    try {
      if (currentTab === "in-fav") {
        const data = await searchFavorites(q);
        if (data.results.length === 0) {
          showInlineMessage(resultEl, "未找到匹配的收藏视频", "muted");
          return;
        }
        let html = `<p style="margin-bottom:12px;">找到 ${data.total} 条结果：</p>`;
        for (const item of data.results) {
          html += `<div class="result-card">
            <a href="${escapeAttr(item.link)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
            <span class="meta" style="margin-left:8px;">— ${escapeHtml(item.upper)}</span>
            <span class="meta" style="float:right;">${escapeHtml(item.folder_name || "")}</span>
          </div>`;
        }
        resultEl.innerHTML = html;
      } else {
        const data = await searchAll(q);
        if (data.results.length === 0) {
          showInlineMessage(resultEl, "未找到相关视频", "muted");
          return;
        }
        let html = "";
        data.results.forEach((item, index) => {
          html += `<div class="result-card" style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <a href="${escapeAttr(item.link)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
              <div class="meta">${escapeHtml(item.upper)}</div>
            </div>
            <button class="btn btn-secondary" data-index="${index}">+ 收藏</button>
          </div>`;
        });
        resultEl.innerHTML = html;

        resultEl.querySelectorAll("[data-index]").forEach(btn => {
          btn.addEventListener("click", () => {
            const item = data.results[Number(btn.dataset.index)];
            showAddModal(item.bvid, item.title);
          });
        });
      }
    } catch (e) {
      showInlineMessage(resultEl, `搜索失败: ${formatError(e)}`);
    } finally {
      spinner.style.display = "none";
    }
  });

  document.getElementById("searchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("searchBtn").click();
  });
}

function showAddModal(bvid, title) {
  const existing = document.getElementById("addModal");
  if (existing) existing.remove();

  const options = cachedFolders.map(f =>
    `<option value="${escapeAttr(f.id || f.media_id || "")}">${escapeHtml(f.title || "收藏夹")}</option>`
  ).join("");

  const modal = document.createElement("div");
  modal.id = "addModal";
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal">
      <h3>加入收藏：${escapeHtml(title)}</h3>
      <select id="addFolderSelect">${options}</select>
      <div class="modal-actions">
        <button id="cancelAddBtn" class="btn btn-secondary">取消</button>
        <button id="confirmAddBtn" class="btn">确认加入</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  document.getElementById("cancelAddBtn").addEventListener("click", () => modal.remove());
  document.getElementById("confirmAddBtn").addEventListener("click", async () => {
    const confirmBtn = document.getElementById("confirmAddBtn");
    const folderId = document.getElementById("addFolderSelect").value || null;
    try {
      setButtonBusy(confirmBtn, true, "加入中…");
      const result = await addToFavorite(bvid, folderId);
      showToast(result.message || (result.success ? "已加入" : "加入失败"));
      modal.remove();
    } catch (e) {
      showToast("操作失败: " + formatError(e), "error");
    } finally {
      setButtonBusy(confirmBtn, false);
    }
  });
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.remove(); });
}
