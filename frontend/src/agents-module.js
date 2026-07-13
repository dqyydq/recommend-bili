import {
  analyzeProfile,
  approveOrganizationPlan,
  buildLearningPath,
  buildFolderStructurePlan,
  buildOrganizationPlan,
  buildLearningProjectPlan,
  chatLearningProject,
  confirmLearningProjectReview,
  confirmLearningProjectWeek,
  createLearningProject,
  executeOrganizationPlan,
  getKnowledgeDashboard,
  getFolderStructurePlans,
  getLearningProject,
  getLearningProjects,
  getOrganizationPlans,
  rebuildSearchIndex,
  semanticSearch,
  updateOrganizationPlanAction,
  updateFolderStructureAction,
  finalizeFolderStructurePlan,
  updateLearningProjectTask,
  reviewLearningProject,
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
        <div class="tab" data-agent-tab="projects">学习项目</div>
        <div class="tab" data-agent-tab="organization">整理计划</div>
        <div class="tab" data-agent-tab="structure">结构蓝图</div>
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
      if (tab.dataset.agentTab === "projects") renderLearningProjectsAgent(content);
      if (tab.dataset.agentTab === "organization") renderOrganizationAgent(content);
      if (tab.dataset.agentTab === "structure") renderFolderStructureAgent(content);
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

function renderLearningProjectsAgent(el) {
  el.innerHTML = `
    <div class="agent-toolbar">
      <input id="projectGoalInput" class="input" style="flex:1" placeholder="例如：4 周掌握 FastAPI 项目开发" />
      <input id="projectWeeksInput" class="input project-number" type="number" min="1" max="52" value="4" title="学习周期（周）" />
      <input id="projectMinutesInput" class="input project-number" type="number" min="15" max="10080" value="180" title="每周分钟数" />
      <button id="createProjectBtn" class="btn">创建项目</button>
    </div>
    <div id="learningProjectsResult"></div>`;
  const result = document.getElementById("learningProjectsResult");
  const load = async () => {
    try {
      const data = await getLearningProjects();
      result.innerHTML = `<div class="agent-plan-list">${(data.projects || []).map(project => `<button class="learning-project-card" data-project-id="${escapeAttr(project.id)}"><strong>${escapeHtml(project.goal)}</strong><span>第 ${Number(project.current_week)} 周 · ${Number(project.weekly_minutes)} 分钟/周</span></button>`).join("") || "<p class=\"muted\">创建一个目标，让 Agent 从收藏中排出第一周任务。</p>"}</div>`;
      result.querySelectorAll("[data-project-id]").forEach(button => button.addEventListener("click", () => openProject(button.dataset.projectId)));
    } catch (e) { showInlineMessage(result, formatError(e, "学习项目加载失败")); }
  };
  const openProject = async id => {
    try {
      const data = await getLearningProject(id);
      renderLearningProjectDetail(data, result, openProject);
    } catch (e) { showInlineMessage(result, formatError(e, "项目加载失败")); }
  };
  document.getElementById("createProjectBtn").addEventListener("click", async () => {
    const goal = document.getElementById("projectGoalInput").value.trim();
    if (!goal) return showToast("先写下一个学习目标", "error");
    try {
      const project = await createLearningProject(goal, Number(document.getElementById("projectWeeksInput").value), Number(document.getElementById("projectMinutesInput").value));
      renderLearningProjectDetail(project, result, openProject);
    } catch (e) { showInlineMessage(result, formatError(e, "创建项目失败")); }
  });
  load();
}

function renderLearningProjectDetail(project, el, reload) {
  const week = Number(project.current_week || 1);
  const tasks = (project.tasks || []).filter(task => Number(task.week_number) === week);
  const review = (project.reviews || []).find(item => Number(item.week_number) === week && item.status === "draft");
  el.innerHTML = `<div class="learning-project-head"><div><strong>${escapeHtml(project.goal)}</strong><p>第 ${week} 周 · ${Number(project.weekly_minutes)} 分钟预算</p></div><button id="projectPlanBtn" class="btn">生成本周草稿</button></div>
    <div class="learning-task-list">${tasks.map(task => `<div class="learning-task"><strong>${escapeHtml(task.title)}</strong><p>${escapeHtml(task.rationale || "")}</p><small>${Number(task.estimated_minutes)} 分钟 · ${escapeHtml(task.state)}</small>${task.favorite_refs?.map(ref => `<a href="${escapeAttr(ref.link || "#")}" target="_blank" rel="noopener">${escapeHtml(ref.title || "相关收藏")}</a>`).join("") || ""}${task.state === "pending" || task.state === "blocked" ? `<div><button data-task="completed" data-task-id="${escapeAttr(task.id)}" class="btn">完成</button><button data-task="blocked" data-task-id="${escapeAttr(task.id)}" class="btn btn-secondary">卡住</button></div>` : ""}</div>`).join("") || "<p class=\"muted\">先生成本周任务草稿。</p>"}</div>
    ${tasks.some(t => t.state === "draft") ? `<div class="agent-plan-footer"><button id="confirmWeekBtn" class="btn">确认本周任务</button></div>` : ""}
    <div class="learning-chat"><div>${(project.messages || []).map(m => `<p class="chat-${escapeAttr(m.role)}">${escapeHtml(m.content)}</p>`).join("")}</div><div class="agent-toolbar"><input id="projectChatInput" class="input" placeholder="例如：我卡在依赖注入，下一步怎么做？" /><button id="projectChatBtn" class="btn">问 Agent</button></div></div>
    <div class="agent-plan-footer"><button id="reviewProjectBtn" class="btn btn-secondary">生成本周回顾</button>${review ? `<button id="confirmReviewBtn" class="btn">确认下周计划</button>` : ""}</div>${review ? `<div class="agent-answer"><strong>本周回顾</strong><p>${escapeHtml(review.summary)}</p></div>` : ""}`;
  document.getElementById("projectPlanBtn").onclick = async e => { setButtonBusy(e.currentTarget, true, "生成中…"); renderLearningProjectDetail(await buildLearningProjectPlan(project.id), el, reload); };
  document.getElementById("confirmWeekBtn")?.addEventListener("click", async () => renderLearningProjectDetail(await confirmLearningProjectWeek(project.id, week), el, reload));
  el.querySelectorAll("[data-task]").forEach(button => button.addEventListener("click", async () => {
    const note = button.dataset.task === "blocked" ? (window.prompt("哪里卡住了？这会帮助 Agent 在回顾时调整计划。") || "") : "";
    renderLearningProjectDetail(await updateLearningProjectTask(project.id, button.dataset.taskId, button.dataset.task, note), el, reload);
  }));
  document.getElementById("projectChatBtn").onclick = async () => { const text = document.getElementById("projectChatInput").value.trim(); if (text) renderLearningProjectDetail(await chatLearningProject(project.id, text), el, reload); };
  document.getElementById("reviewProjectBtn").onclick = async () => renderLearningProjectDetail(await reviewLearningProject(project.id), el, reload);
  document.getElementById("confirmReviewBtn")?.addEventListener("click", async () => renderLearningProjectDetail(await confirmLearningProjectReview(project.id, week), el, reload));
}

function renderFolderStructureAgent(el) {
  el.innerHTML = `
    <div class="agent-toolbar">
      <input id="structureGoalInput" class="input" style="flex:1" value="按用途与主题重建收藏夹结构" />
      <button id="structureBuildBtn" class="btn">生成结构蓝图</button>
      <button id="structureHistoryBtn" class="btn btn-secondary">历史蓝图</button>
    </div>
    <div class="agent-hint">蓝图只读取本地收藏快照。确认后会保留审核队列，第一版不会直接移动或删除 B 站收藏。</div>
    <div id="structureResult"></div>`;
  const result = document.getElementById("structureResult");
  const build = async () => {
    const goal = document.getElementById("structureGoalInput").value.trim();
    if (!goal) return showToast("请输入整理目标", "error");
    try {
      const button = document.getElementById("structureBuildBtn");
      setButtonBusy(button, true, "构建中…");
      result.innerHTML = loadingBlock("结构 Agent 正在把收藏归入用途和主题…");
      renderFolderStructurePlan(await buildFolderStructurePlan(goal), result);
    } catch (e) { showInlineMessage(result, formatError(e, "结构蓝图生成失败")); }
    finally { setButtonBusy(document.getElementById("structureBuildBtn"), false); }
  };
  document.getElementById("structureBuildBtn").addEventListener("click", build);
  document.getElementById("structureHistoryBtn").addEventListener("click", async () => {
    try {
      const data = await getFolderStructurePlans();
      result.innerHTML = `<div class="agent-plan-list">${(data.plans || []).map(plan => `<div class="agent-plan-card"><div><strong>${escapeHtml(plan.goal)}</strong><p>${Number(plan.action_count)} 个目标文件夹</p></div><span class="agent-plan-status">${escapeHtml(plan.status)}</span></div>`).join("") || "<p class=\"muted\">暂无结构蓝图</p>"}</div>`;
    } catch (e) { showInlineMessage(result, formatError(e, "历史蓝图加载失败")); }
  });
}

function renderFolderStructurePlan(plan, el) {
  const draft = plan.status === "draft";
  const actions = plan.actions || [];
  el.innerHTML = `<div class="agent-answer"><div class="agent-kicker">Folder Structure Agent</div><p><strong>${escapeHtml(plan.goal || "收藏夹结构蓝图")}</strong></p><small>${Number(plan.action_count || actions.length)} 个目标文件夹 · ${draft ? "等待审核" : "审核已确认"}</small></div>
    <div class="structure-tree">${actions.map(action => {
      const samples = (action.items || []).slice(0, 3);
      return `<div class="structure-branch"><div class="structure-branch-head"><div><span class="structure-purpose">${escapeHtml(action.purpose)}</span><strong>${escapeHtml(action.topic)}</strong><small>${Number(action.item_count)} 条 · 置信度 ${Math.round(Number(action.confidence || 0) * 100)}%</small></div><span class="agent-plan-status">${action.review_state === "approved" ? "已保留" : action.review_state === "skipped" ? "已跳过" : "待审核"}</span></div><ul>${samples.map(item => `<li><a href="${escapeAttr(item.link || "#")}" target="_blank" rel="noopener">${escapeHtml(item.title || "未命名收藏")}</a><span>${escapeHtml(item.source_folder || "")}</span></li>`).join("")}</ul>${Number(action.item_count) > samples.length ? `<small>另有 ${Number(action.item_count) - samples.length} 条</small>` : ""}${draft ? `<div class="agent-plan-action-buttons"><button class="btn btn-secondary" data-structure-state="skipped" data-structure-id="${escapeAttr(action.id)}">跳过</button><button class="btn" data-structure-state="approved" data-structure-id="${escapeAttr(action.id)}">保留目标文件夹</button></div>` : ""}</div>`;
    }).join("")}</div>${draft ? `<div class="agent-plan-footer"><button id="finalizeStructureBtn" class="btn">确认结构蓝图</button></div>` : ""}`;
  if (draft) {
    el.querySelectorAll("[data-structure-state]").forEach(button => button.addEventListener("click", async () => {
      renderFolderStructurePlan(await updateFolderStructureAction(plan.id, button.dataset.structureId, button.dataset.structureState), el);
    }));
    document.getElementById("finalizeStructureBtn").addEventListener("click", async event => {
      try {
        setButtonBusy(event.currentTarget, true, "确认中…");
        renderFolderStructurePlan(await finalizeFolderStructurePlan(plan.id), el);
        showToast("结构蓝图已确认。远程移动将在接口验证后开放。", "success");
      } catch (e) { showToast(formatError(e, "确认蓝图失败"), "error"); }
    });
  }
}

function renderOrganizationAgent(el) {
  el.innerHTML = `
    <div class="agent-toolbar">
      <input id="organizationGoalInput" class="input" style="flex:1;" placeholder="例如：清理重复教程，保留真正想看的内容" />
      <button id="organizationPlanBtn" class="btn">生成计划</button>
      <button id="organizationHistoryBtn" class="btn btn-secondary">历史计划</button>
    </div>
    <div id="organizationResult"></div>
  `;

  const input = document.getElementById("organizationGoalInput");
  const planBtn = document.getElementById("organizationPlanBtn");
  const historyBtn = document.getElementById("organizationHistoryBtn");
  const result = document.getElementById("organizationResult");

  async function generate() {
    const goal = input.value.trim();
    if (!goal) {
      showToast("请输入整理目标", "error");
      return;
    }
    try {
      setButtonBusy(planBtn, true, "生成中…");
      result.innerHTML = loadingBlock("整理 Agent 正在检查重复和长期未处理的收藏…");
      const plan = await buildOrganizationPlan(goal);
      renderOrganizationPlan(plan, result);
    } catch (e) {
      showInlineMessage(result, formatError(e, "整理计划生成失败"));
    } finally {
      setButtonBusy(planBtn, false);
    }
  }

  planBtn.addEventListener("click", generate);
  input.addEventListener("keydown", event => {
    if (event.key === "Enter") generate();
  });
  historyBtn.addEventListener("click", async () => {
    try {
      setButtonBusy(historyBtn, true, "加载中…");
      const data = await getOrganizationPlans();
      renderOrganizationHistory(data.plans || [], result);
    } catch (e) {
      showInlineMessage(result, formatError(e, "加载历史计划失败"));
    } finally {
      setButtonBusy(historyBtn, false);
    }
  });
}

function renderOrganizationHistory(plans, el) {
  if (!plans.length) {
    showInlineMessage(el, "暂无整理计划", "muted");
    return;
  }
  el.innerHTML = `<div class="agent-plan-list">${plans.map(plan => `
    <div class="agent-plan-card">
      <div><strong>${escapeHtml(plan.goal)}</strong><p>${escapeHtml(plan.summary || "")}</p></div>
      <span class="agent-plan-status">${escapeHtml(plan.status)}</span>
      <small>${Number(plan.action_count || 0)} 项</small>
    </div>
  `).join("")}</div>`;
}

function renderOrganizationPlan(plan, el) {
  const actions = plan.actions || [];
  const isDraft = plan.status === "draft";
  const canExecute = plan.status === "approved" && ["idle", "partial_failed", "failed"].includes(plan.execution_status || "idle");
  const executionLabel = organizationExecutionLabel(plan.execution_status || "idle");
  const counts = plan.execution_counts || {};
  el.innerHTML = `
    <div class="agent-answer">
      <div class="agent-kicker">Organization Plan Agent</div>
      <p><strong>${escapeHtml(plan.goal || "整理目标")}</strong></p>
      <p>${escapeHtml(plan.summary || "")}</p>
      <small>${Number(plan.action_count || actions.length)} 项待审核 · ${escapeHtml(executionLabel)}</small>
    </div>
    <div class="agent-plan-actions">
      ${actions.map(action => renderOrganizationAction(action, isDraft)).join("") || `<p class="muted">没有可审核的动作</p>`}
    </div>
    ${Object.keys(counts).length ? `<p class="agent-execution-summary">已删除 ${Number(counts.deleted || 0)} 项，仍有效 ${Number(counts.skipped_valid || 0)} 项，无法验证 ${Number(counts.skipped_unreachable || 0)} 项，失败 ${Number(counts.failed || 0)} 项。</p>` : ""}
    ${isDraft ? `<div class="agent-plan-footer"><button id="approveOrganizationPlanBtn" class="btn">确认计划</button></div>` : ""}
    ${canExecute ? `<div class="agent-plan-footer"><button id="executeOrganizationPlanBtn" class="btn btn-danger">执行已确认的失效项清理</button></div>` : ""}
  `;

  if (isDraft) {
    el.querySelectorAll("[data-plan-action]").forEach(button => {
      button.addEventListener("click", async () => {
        try {
          setButtonBusy(button, true, "更新中…");
          const updated = await updateOrganizationPlanAction(plan.id, button.dataset.actionId, button.dataset.planAction);
          renderOrganizationPlan(updated, el);
        } catch (e) {
          showToast(formatError(e, "更新动作失败"), "error");
          setButtonBusy(button, false);
        }
      });
    });
    document.getElementById("approveOrganizationPlanBtn")?.addEventListener("click", async event => {
      try {
        setButtonBusy(event.currentTarget, true, "确认中…");
        const updated = await approveOrganizationPlan(plan.id);
        renderOrganizationPlan(updated, el);
        showToast("计划已确认", "success");
      } catch (e) {
        showToast(formatError(e, "确认计划失败"), "error");
        setButtonBusy(event.currentTarget, false);
      }
    });
  }

  document.getElementById("executeOrganizationPlanBtn")?.addEventListener("click", async event => {
    if (!window.confirm("系统会再次确认每个条目已失效，只删除复核失败的条目。删除后无法恢复，是否继续？")) return;
    try {
      setButtonBusy(event.currentTarget, true, "复核并执行中...");
      const updated = await executeOrganizationPlan(plan.id);
      renderOrganizationPlan(updated, el);
      showToast("执行完成，已保存每一项的复核结果。", "success");
    } catch (e) {
      showToast(formatError(e, "执行整理计划失败"), "error");
      setButtonBusy(event.currentTarget, false);
    }
  });
}

function renderOrganizationAction(action, isDraft) {
  const actionName = action.action_type === "review_duplicate" ? "重复收藏复核" : "长期未处理复核";
  const stateName = action.state === "skipped" ? "已跳过" : action.state === "approved" ? "已保留" : "待审核";
  const execution = organizationActionExecutionLabel(action.execution_state || "pending");
  return `<div class="agent-plan-action">
    <div class="agent-plan-action-head">
      <span class="agent-risk agent-risk-${escapeAttr(action.risk || "low")}">${escapeHtml(actionName)}</span>
      <span class="agent-plan-status">${escapeHtml(stateName)}</span>
    </div>
    <a href="${escapeAttr(`https://www.bilibili.com/video/${action.bvid || ""}`)}" target="_blank" rel="noopener">${escapeHtml(action.title)}</a>
    <p>${escapeHtml(action.reason || "")}</p>
    <small>${escapeHtml(action.folder_name || "")}</small>
    ${action.execution_state && action.execution_state !== "pending" ? `<div class="agent-execution-result"><strong>${escapeHtml(execution)}</strong><span>${escapeHtml(action.execution_message || "")}</span></div>` : ""}
    ${isDraft ? `<div class="agent-plan-action-buttons">
      <button class="btn btn-secondary" data-plan-action="skipped" data-action-id="${escapeAttr(action.id)}">跳过</button>
      <button class="btn" data-plan-action="approved" data-action-id="${escapeAttr(action.id)}">保留复核</button>
    </div>` : ""}
  </div>`;
}

function organizationExecutionLabel(state) {
  return ({ idle: "等待执行", running: "正在执行", completed: "执行完成", partial_failed: "部分完成，可重试", failed: "执行失败，可重试" })[state] || "等待执行";
}

function organizationActionExecutionLabel(state) {
  return ({ deleted: "已删除", skipped_valid: "仍然有效，未删除", skipped_unreachable: "无法验证，未删除", failed: "删除失败", pending: "等待执行" })[state] || "等待执行";
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
