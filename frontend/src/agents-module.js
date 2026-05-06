import { analyzeProfile, rebuildSearchIndex, semanticSearch } from "./api.js";
import { escapeAttr, escapeHtml, formatError, setButtonBusy, showInlineMessage, showToast } from "./ui.js";

export function renderAgentsModule(container) {
  container.innerHTML = `
    <div>
      <div class="tabs">
        <div class="tab active" data-agent-tab="profile">收藏人格</div>
        <div class="tab" data-agent-tab="retrieval">智能检索</div>
      </div>
      <div id="agentContent"></div>
    </div>
  `;

  const content = document.getElementById("agentContent");
  document.querySelectorAll("[data-agent-tab]").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("[data-agent-tab]").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      if (tab.dataset.agentTab === "profile") renderProfileAgent(content);
      if (tab.dataset.agentTab === "retrieval") renderRetrievalAgent(content);
    });
  });

  renderProfileAgent(content);
}

function renderProfileAgent(el) {
  el.innerHTML = `
    <div class="agent-toolbar">
      <button id="profileAnalyzeBtn" class="btn">生成我的收藏人格</button>
      <span class="agent-hint">会读取收藏标题、UP 主、收藏夹和时间分布，生成一张有点懂你的卡片。</span>
    </div>
    <div id="profileResult"></div>
  `;

  const btn = document.getElementById("profileAnalyzeBtn");
  const result = document.getElementById("profileResult");
  btn.addEventListener("click", async () => {
    try {
      setButtonBusy(btn, true, "分析中…");
      result.innerHTML = loadingBlock("画像 Agent 正在翻你的收藏夹…");
      const data = await analyzeProfile();
      renderProfileResult(data, result);
    } catch (e) {
      showInlineMessage(result, formatError(e, "画像生成失败"));
    } finally {
      setButtonBusy(btn, false);
    }
  });
}

function renderProfileResult(data, el) {
  const tags = data.tags || [];
  const radar = data.radar || [];
  const insights = data.insights || [];
  const roasts = data.roasts || [];
  const actions = data.actions || [];

  const radarHtml = radar.map(item => {
    const score = Math.max(0, Math.min(100, Number(item.score || 0)));
    return `<div class="agent-meter">
      <div class="agent-meter-label">
        <span>${escapeHtml(item.label)}</span>
        <strong>${score}</strong>
      </div>
      <div class="agent-meter-track"><div style="width:${score}%"></div></div>
    </div>`;
  }).join("");

  el.innerHTML = `
    <div class="agent-profile">
      <div class="agent-profile-head">
        <div>
          <div class="agent-kicker">Favorite Persona Agent</div>
          <h2>${escapeHtml(data.persona || "收藏探索家")}</h2>
          <p>${escapeHtml(data.subtitle || "你的收藏里藏着一条很有个人风格的兴趣路线。")}</p>
        </div>
        <div class="agent-score-card">
          <strong>${Number(data.total || 0)}</strong>
          <span>条收藏</span>
          <small>${Number(data.folders_count || 0)} 个收藏夹 · ${Number(data.dust_count || 0)} 个高吃灰风险</small>
        </div>
      </div>
      <div class="agent-tags">${tags.map(tag => `<span>${escapeHtml(tag)}</span>`).join("")}</div>
      <div class="agent-grid">
        <div class="agent-panel">
          <h3>兴趣雷达</h3>
          ${radarHtml || `<p class="muted">暂无雷达数据</p>`}
        </div>
        <div class="agent-panel">
          <h3>Agent 观察</h3>
          <ul>${insights.map(text => `<li>${escapeHtml(text)}</li>`).join("")}</ul>
        </div>
        <div class="agent-panel">
          <h3>轻度吐槽</h3>
          <ul>${roasts.map(text => `<li>${escapeHtml(text)}</li>`).join("")}</ul>
        </div>
        <div class="agent-panel">
          <h3>今日行动</h3>
          <ul>${actions.map(text => `<li>${escapeHtml(text)}</li>`).join("")}</ul>
        </div>
      </div>
    </div>
  `;
}

function renderRetrievalAgent(el) {
  el.innerHTML = `
    <div class="agent-toolbar">
      <input id="agentSearchInput" class="input" style="flex:1;" placeholder="比如：找几个适合今晚补的 Python / AI Agent / 剪辑教程" />
      <button id="agentSearchBtn" class="btn">智能检索</button>
      <button id="agentRefreshBtn" class="btn btn-secondary">重建索引</button>
    </div>
    <div class="agent-hint" style="margin-bottom:14px;">首次检索会自动建立 Chroma 索引；如果刚整理过收藏夹，可以点重建索引。</div>
    <div id="agentSearchResult"></div>
  `;

  const input = document.getElementById("agentSearchInput");
  const searchBtn = document.getElementById("agentSearchBtn");
  const refreshBtn = document.getElementById("agentRefreshBtn");
  const result = document.getElementById("agentSearchResult");

  async function runSearch(refresh = false) {
    const q = input.value.trim();
    if (!q) {
      showToast("先输入你想找什么", "error");
      return;
    }
    try {
      setButtonBusy(searchBtn, true, refresh ? "重建并检索…" : "检索中…");
      result.innerHTML = loadingBlock(refresh ? "检索 Agent 正在重建 Chroma 索引…" : "检索 Agent 正在语义匹配收藏夹…");
      const data = await semanticSearch(q, { refresh });
      renderSearchResult(data, result);
    } catch (e) {
      showInlineMessage(result, formatError(e, "智能检索失败"));
    } finally {
      setButtonBusy(searchBtn, false);
    }
  }

  searchBtn.addEventListener("click", () => runSearch(false));
  input.addEventListener("keydown", e => {
    if (e.key === "Enter") runSearch(false);
  });
  refreshBtn.addEventListener("click", async () => {
    try {
      setButtonBusy(refreshBtn, true, "重建中…");
      result.innerHTML = loadingBlock("正在抓取收藏并写入 Chroma…");
      const data = await rebuildSearchIndex();
      showToast(`索引已更新：${data.indexed || 0} 条收藏`, "success");
      showInlineMessage(result, `索引已更新：${data.indexed || 0} 条收藏`, "success");
    } catch (e) {
      showInlineMessage(result, formatError(e, "索引重建失败"));
    } finally {
      setButtonBusy(refreshBtn, false);
    }
  });
}

function renderSearchResult(data, el) {
  const results = data.results || [];
  const resultHtml = results.map(item => `<div class="agent-result-item">
    <div>
      <a href="${escapeAttr(item.link)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
      <div class="meta">${escapeHtml(item.upper)} · ${escapeHtml(item.folder_name)} · 相关度 ${escapeHtml(item.score)}</div>
    </div>
  </div>`).join("");

  el.innerHTML = `
    <div class="agent-answer">
      <div class="agent-kicker">Retrieval Agent · Chroma</div>
      <p>${escapeHtml(data.answer || "我找到了这些相关收藏。").replaceAll("\n", "<br>")}</p>
      <small>当前索引：${Number(data.indexed || 0)} 条收藏</small>
    </div>
    <div class="agent-results">
      ${resultHtml || `<p class="muted">没有找到相关收藏</p>`}
    </div>
  `;
}

function loadingBlock(text) {
  return `<div class="bili-loading">
    <div class="dots-row"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
    <div class="status-text">${escapeHtml(text)}</div>
  </div>`;
}
