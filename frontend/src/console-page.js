import { logout } from "./api.js";
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

  // 默认加载整理收藏夹
  renderClassifyModule(contentArea);
}
