import {
  analyzeProfile,
  buildLearningPath,
  getKnowledgeDashboard,
  rebuildSearchIndex,
  semanticSearch,
} from "./api.js";
import { escapeAttr, escapeHtml, formatError, setButtonBusy, showInlineMessage, showToast } from "./ui.js";

export function renderAgentsModule(container) {
  container.innerHTML = `
    <div>
      <div class="tabs">
        <div class="tab active" data-agent-tab="dashboard">知识库首页</div>
        <div class="tab" data-agent-tab="profile">收藏人格</div>
        <div class="tab" data-agent-tab="retrieval">智能检索</div>
        <div class="tab" data-agent-tab="learning">学习路线</div>
      </div>
      <div id="agentContent"></div>
    </div>
  `;

  const content = document.getElementById("agentContent");
  document.querySelectorAll("[data-agent-tab]").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("[data-agent-tab]").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      if (tab.dataset.agentTab === "dashboard") renderDashboardAgent(content);
      if (tab.dataset.agentTab === "profile") renderProfileAgent(content);
      if (tab.dataset.agentTab === "retrieval") renderRetrievalAgent(content);
      if (tab.dataset.agentTab === "learning") renderLearningAgent(content);
    });
  });

  renderDashboardAgent(content);
}

function renderDashboardAgent(el) {
  el.innerHTML = `
    <div class="agent-toolbar">
      <button id="dashboardRefreshBtn" class="btn">刷新知识库状态</button>
      <span class="agent-hint">首页聚合收藏规模、吃灰风险、索引状态和今日行动。</span>
    </div>
    <div id="dashboardResult">${loadingBlock("正在读取收藏知识库状态…")}</div>
  `;

  const btn = document.getElementById("dashboardRefreshBtn");
  const result = document.getElementById("dashboardResult");

  async function loadDashboard() {
    try {
      setButtonBusy(btn, true, "刷新中…");
      result.innerHTML = loadingBlock("正在读取收藏知识库状态…");
      const data = await getKnowledgeDashboard();
      renderDashboardResult(data, result);
    } catch (e) {
      showInlineMessage(result, formatError(e, "知识库状态加载失败"));
    } finally {
      setButtonBusy(btn, false);
    }
  }

  btn.addEventListener("click", loadDashboard);
  loadDashboard();
}

function renderDashboardResult(data, el) {
  const topFolders = data.top_folders || [];
  const recentItems = data.recent_items || [];
  const cleanup = data.cleanup_candidates || [];
  const actions = data.today_actions || [];
  el.innerHTML = `
    <div class="agent-dashboard">
      <div class="agent-stat-grid">
        ${statCard("收藏总数", data.total || 0, "条")}
        ${statCard("收藏夹", data.folders_count || 0, "个")}
        ${statCard("已索引", data.indexed || 0, "条")}
        ${statCard("健康度", data.health_score || 0, "分")}
      </div>
      <div class="agent-grid" style="margin-top:14px;">
        <div class="agent-panel">
          <h3>今日行动</h3>
          <ul>${actions.map(text => `<li>${escapeHtml(text)}</li>`).join("")}</ul>
        </div>
        <div class="agent-panel">
          <h3>主要收藏夹</h3>
          ${topFolders.map(item => meterLine(item.name, item.count, data.total || 1)).join("") || `<p class="muted">暂无数据</p>`}
        </div>
        <div class="agent-panel">
          <h3>最近新增</h3>
          ${renderCompactItems(recentItems)}
        </div>
        <div class="agent-panel">
          <h3>优先清理线索</h3>
          ${renderCompactItems(cleanup)}
        </div>
      </div>
    </div>
  `;
}

function statCard(label, value, unit) {
  return `<div class="agent-stat-card">
    <span>${escapeHtml(label)}</span>
    <strong>${Number(value || 0)}</strong>
    <small>${escapeHtml(unit)}</small>
  </div>`;
}

function meterLine(label, value, total) {
  const pct = Math.max(4, Math.min(100, Math.round(Number(value || 0) / Math.max(1, Number(total || 1)) * 100)));
  return `<div class="agent-meter">
    <div class="agent-meter-label"><span>${escapeHtml(label)}</span><strong>${Number(value || 0)}</strong></div>
    <div class="agent-meter-track"><div style="width:${pct}%"></div></div>
  </div>`;
}

function renderCompactItems(items) {
  if (!items.length) return `<p class="muted">暂无数据</p>`;
  return `<ul class="agent-compact-list">${items.map(item => `<li>
    <a href="${escapeAttr(item.link)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
    <span>${escapeHtml(item.upper || "")} · ${escapeHtml(item.folder_name || "")}</span>
  </li>`).join("")}</ul>`;
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
      <div class="agent-reason">${escapeHtml(item.reason || "语义相似度较高")}</div>
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

function renderLearningAgent(el) {
  el.innerHTML = `
    <div class="agent-toolbar">
      <input id="learningGoalInput" class="input" style="flex:1;" placeholder="比如：我想用一周学会 FastAPI 项目开发" />
      <button id="learningBtn" class="btn">生成路线</button>
      <button id="learningRefreshBtn" class="btn btn-secondary">重建索引后生成</button>
    </div>
    <div class="agent-hint" style="margin-bottom:14px;">学习路线会先语义检索收藏，再按阶段组织成可执行计划。</div>
    <div id="learningResult"></div>
  `;

  const input = document.getElementById("learningGoalInput");
  const btn = document.getElementById("learningBtn");
  const refreshBtn = document.getElementById("learningRefreshBtn");
  const result = document.getElementById("learningResult");

  async function run(refresh = false) {
    const goal = input.value.trim();
    if (!goal) {
      showToast("先输入学习目标", "error");
      return;
    }
    const activeBtn = refresh ? refreshBtn : btn;
    try {
      setButtonBusy(activeBtn, true, refresh ? "重建并生成…" : "生成中…");
      result.innerHTML = loadingBlock("学习路线 Agent 正在从收藏夹里排课…");
      const data = await buildLearningPath(goal, { refresh });
      renderLearningResult(data, result);
    } catch (e) {
      showInlineMessage(result, formatError(e, "学习路线生成失败"));
    } finally {
      setButtonBusy(activeBtn, false);
    }
  }

  btn.addEventListener("click", () => run(false));
  refreshBtn.addEventListener("click", () => run(true));
  input.addEventListener("keydown", e => {
    if (e.key === "Enter") run(false);
  });
}

function renderLearningResult(data, el) {
  const stages = data.stages || [];
  const warnings = data.warnings || [];
  el.innerHTML = `
    <div class="agent-answer">
      <div class="agent-kicker">Learning Path Agent</div>
      <p><strong>${escapeHtml(data.goal || "学习目标")}</strong></p>
      <p>${escapeHtml(data.summary || "已根据收藏内容生成路线。")}</p>
      <small>当前索引：${Number(data.indexed || 0)} 条收藏</small>
    </div>
    ${warnings.length ? `<div class="agent-warning">${warnings.map(text => escapeHtml(text)).join("<br>")}</div>` : ""}
    <div class="agent-stage-list">
      ${stages.map((stage, index) => renderStage(stage, index)).join("") || `<p class="muted">没有生成有效路线</p>`}
    </div>
  `;
}

function renderStage(stage, index) {
  const items = stage.items || [];
  return `<div class="agent-stage">
    <div class="agent-stage-index">${index + 1}</div>
    <div class="agent-stage-body">
      <h3>${escapeHtml(stage.title || `阶段 ${index + 1}`)}</h3>
      <p>${escapeHtml(stage.purpose || "")}</p>
      <ul class="agent-compact-list">
        ${items.map(item => `<li>
          <a href="${escapeAttr(item.link)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
          <span>${escapeHtml(item.upper || "")} · ${escapeHtml(item.folder_name || "")}</span>
          ${item.reason ? `<em>${escapeHtml(item.reason)}</em>` : ""}
        </li>`).join("")}
      </ul>
      ${stage.task ? `<div class="agent-task">阶段任务：${escapeHtml(stage.task)}</div>` : ""}
    </div>
  </div>`;
}

function loadingBlock(text) {
  return `<div class="bili-loading">
    <div class="dots-row"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
    <div class="status-text">${escapeHtml(text)}</div>
  </div>`;
}
