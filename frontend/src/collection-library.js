import { getFavorites, getFolders, searchFavorites } from "./api.js";
import { escapeAttr, escapeHtml, formatError, setButtonBusy, showInlineMessage } from "./ui.js";
import { renderClassifyModule } from "./classify-module.js";
import { renderDustModule } from "./dust-module.js";

export function renderCollectionLibrary(container) {
  container.innerHTML = `
    <div class="destination-head">
      <div><span class="eyebrow">本地数据源</span><h1>收藏库</h1><p>浏览、检索与分析已经同步到本地的收藏。</p></div>
      <div class="destination-actions">
        <button class="btn btn-secondary" data-library-tool="classify" type="button">主题分析</button>
        <button class="btn btn-secondary" data-library-tool="health" type="button">健康检查</button>
      </div>
    </div>
    <section id="libraryBrowser" class="library-browser">
      <aside class="folder-rail">
        <div class="rail-heading"><strong>收藏夹</strong><span id="folderCount">0</span></div>
        <div id="folderList" class="folder-list"><div class="skeleton-line"></div></div>
      </aside>
      <div class="library-content">
        <form id="librarySearchForm" class="library-search">
          <input id="librarySearchInput" class="input" placeholder="搜索标题、UP 主或语义主题" />
          <button id="librarySearchBtn" class="btn" type="submit">搜索</button>
        </form>
        <div class="library-result-head"><strong id="libraryResultTitle">选择一个收藏夹</strong><span id="libraryResultCount"></span></div>
        <div id="libraryResults" class="video-list"><p class="empty-state">从左侧选择收藏夹，或直接搜索全部本地收藏。</p></div>
      </div>
    </section>
    <section id="libraryToolView" class="library-tool-view" hidden></section>`;

  const browser = document.getElementById("libraryBrowser");
  const toolView = document.getElementById("libraryToolView");
  container.querySelectorAll("[data-library-tool]").forEach(button => {
    button.addEventListener("click", () => {
      browser.hidden = true;
      toolView.hidden = false;
      toolView.innerHTML = `<button class="text-button back-button" id="backToLibrary" type="button">← 返回收藏库</button><div id="embeddedTool"></div>`;
      document.getElementById("backToLibrary").addEventListener("click", () => { toolView.hidden = true; browser.hidden = false; });
      const target = document.getElementById("embeddedTool");
      button.dataset.libraryTool === "classify" ? renderClassifyModule(target) : renderDustModule(target);
    });
  });

  loadFolders();
  const form = document.getElementById("librarySearchForm");
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const q = document.getElementById("librarySearchInput").value.trim();
    if (!q) return;
    const button = document.getElementById("librarySearchBtn");
    try {
      setButtonBusy(button, true, "搜索中…");
      const data = await searchFavorites(q);
      renderVideos(data.results || [], `“${q}”的搜索结果`);
    } catch (error) {
      showInlineMessage(document.getElementById("libraryResults"), formatError(error, "搜索失败"));
    } finally { setButtonBusy(button, false); }
  });
}

async function loadFolders() {
  const list = document.getElementById("folderList");
  try {
    const data = await getFolders();
    const folders = data.folders || [];
    document.getElementById("folderCount").textContent = String(folders.length);
    list.innerHTML = folders.map(folder => `<button type="button" data-folder-id="${escapeAttr(folder.id || folder.media_id)}" data-folder-title="${escapeAttr(folder.title)}"><span>${escapeHtml(folder.title)}</span><small>${Number(folder.media_count || 0)}</small></button>`).join("") || `<p class="empty-state">暂无本地收藏夹，请先同步。</p>`;
    list.querySelectorAll("[data-folder-id]").forEach(button => button.addEventListener("click", async () => {
      list.querySelectorAll("button").forEach(item => item.classList.remove("active"));
      button.classList.add("active");
      const results = document.getElementById("libraryResults");
      results.innerHTML = `<div class="skeleton-line"></div>`;
      try {
        const favorites = await getFavorites(button.dataset.folderId);
        renderVideos(favorites.items || [], button.dataset.folderTitle);
      } catch (error) { showInlineMessage(results, formatError(error, "收藏加载失败")); }
    }));
    list.querySelector("button")?.click();
  } catch (error) {
    showInlineMessage(list, formatError(error, "收藏夹加载失败"));
  }
}

function renderVideos(items, title) {
  document.getElementById("libraryResultTitle").textContent = title;
  document.getElementById("libraryResultCount").textContent = `${items.length} 条`;
  document.getElementById("libraryResults").innerHTML = items.map(item => `<article class="video-row">
    ${item.cover ? `<img src="${escapeAttr(item.cover)}" alt="" loading="lazy" />` : `<div class="video-cover-placeholder"></div>`}
    <div><a href="${escapeAttr(item.link || `https://www.bilibili.com/video/${item.bvid || ""}`)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a><p>${escapeHtml(item.intro || "暂无简介")}</p><span>${escapeHtml(item.upper || "未知 UP 主")} · ${escapeHtml(item.folder_name || item.source_folder || "收藏夹")}</span></div>
  </article>`).join("") || `<p class="empty-state">这里暂时没有收藏内容。</p>`;
}
