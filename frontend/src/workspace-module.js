import {
  chatWithAgent,
  createLearningProject,
  getFolderStructurePlans,
  getKnowledgeDashboard,
  getLearningProjects,
  getAgentSuggestions,
  getOrganizationPlans,
  saveFavoriteFeedback,
  updateAgentSuggestion,
} from "./api.js";
import { escapeAttr, escapeHtml, formatError, setButtonBusy, showInlineMessage, showToast } from "./ui.js";
import { renderSafeMarkdown } from "./markdown.js";

export function renderWorkspaceModule(container, { navigate }) {
  container.innerHTML = `
    <div class="workspace-grid">
      <main class="workspace-main">
        <section class="command-center" aria-labelledby="commandTitle">
          <div class="section-heading">
            <div>
              <span class="eyebrow">Agent 工作台</span>
              <h1 id="commandTitle">今天想从收藏里得到什么？</h1>
            </div>
            <span class="agent-state"><i></i> 可执行</span>
          </div>
          <form id="agentCommandForm" class="command-form">
            <textarea id="agentCommandInput" rows="3" placeholder="例如：找出适合今晚学习的 FastAPI 视频，并告诉我先看哪一个"></textarea>
            <div class="command-actions">
              <div class="command-suggestions" aria-label="推荐指令">
                <button type="button" data-command="找出适合今晚学习的 3 个视频">今晚学什么</button>
                <button type="button" data-command="分析我的收藏夹结构并生成一个整理蓝图">规划收藏结构</button>
                <button type="button" data-command="找出我收藏中长期没有处理的内容">检查积压内容</button>
              </div>
              <button id="agentCommandBtn" class="btn command-submit" type="submit">交给 Agent</button>
            </div>
          </form>
          <div id="commandResult" class="command-result" aria-live="polite"></div>
        </section>

        <section class="workspace-section" aria-labelledby="currentWorkTitle">
          <div class="section-heading compact">
            <div><span class="eyebrow">继续推进</span><h2 id="currentWorkTitle">当前工作</h2></div>
          </div>
          <div id="currentWork" class="work-list"><div class="skeleton-line"></div></div>
        </section>

        <section class="workspace-section" aria-labelledby="insightTitle">
          <div class="section-heading compact">
            <div><span class="eyebrow">本地知识库</span><h2 id="insightTitle">收藏洞察</h2></div>
            <button class="text-button" id="openLibraryBtn" type="button">查看收藏库</button>
          </div>
          <div id="workspaceInsights" class="insight-strip"><div class="skeleton-line"></div></div>
        </section>
      </main>

      <aside class="workspace-context" aria-label="工作台上下文">
        <section class="context-section">
          <span class="eyebrow">今日建议</span>
          <div id="todayActions"><div class="skeleton-line"></div></div>
        </section>
        <section class="context-section">
          <div class="context-heading"><span class="eyebrow">学习进度</span><button class="text-button" data-go="learning" type="button">管理</button></div>
          <div id="projectProgress"><div class="skeleton-line"></div></div>
        </section>
        <section class="context-section">
          <div class="context-heading"><span class="eyebrow">待确认</span><button class="text-button" data-go="operations" type="button">全部</button></div>
          <div id="pendingReviews"><div class="skeleton-line"></div></div>
        </section>
      </aside>
    </div>`;

  container.querySelectorAll("[data-go]").forEach(button => {
    button.addEventListener("click", () => navigate(button.dataset.go));
  });
  document.getElementById("openLibraryBtn").addEventListener("click", () => navigate("library"));

  const form = document.getElementById("agentCommandForm");
  const input = document.getElementById("agentCommandInput");
  const result = document.getElementById("commandResult");
  const submit = document.getElementById("agentCommandBtn");
  let sessionId = null;

  container.querySelectorAll("[data-command]").forEach(button => {
    button.addEventListener("click", () => {
      input.value = button.dataset.command;
      input.focus();
    });
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const command = input.value.trim();
    if (!command) return input.focus();
    try {
      setButtonBusy(submit, true, "分析中…");
      result.innerHTML = `<div class="agent-processing"><span></span>正在判断任务并调用合适的 Agent 工具</div>`;
      const data = await chatWithAgent(command, sessionId);
      sessionId = data.session_id;
      const items = data.citations || [];
      const actions = data.suggested_actions || [];
      result.innerHTML = `
        <div class="agent-response-head"><span class="eyebrow">Agent 结论</span><div class="markdown-answer">${renderSafeMarkdown(data.answer_markdown || "任务已完成。")}</div></div>
        ${items.length ? `<div class="evidence-list">${items.map(item => `<article class="evidence-item"><a href="${escapeAttr(item.link)}" target="_blank" rel="noopener"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.upper || "未知 UP 主")} · ${escapeHtml(item.folder_name || "收藏夹")} · 综合分 ${escapeHtml(item.score || "-")}</span></a><div class="evidence-feedback"><button data-feedback="useful" data-folder-id="${Number(item.folder_id)}" data-media-id="${Number(item.media_id)}" type="button">有用</button><button data-feedback="ignored" data-folder-id="${Number(item.folder_id)}" data-media-id="${Number(item.media_id)}" type="button">忽略</button><button data-feedback="watched" data-folder-id="${Number(item.folder_id)}" data-media-id="${Number(item.media_id)}" type="button">已看</button><button data-feedback="later" data-folder-id="${Number(item.folder_id)}" data-media-id="${Number(item.media_id)}" type="button">稍后</button></div></article>`).join("")}</div>` : ""}
        ${actions.length ? `<div class="agent-suggested-actions">${actions.map(action => `<button class="btn btn-secondary" type="button" data-result-go="${escapeAttr(action.destination || "workspace")}">${escapeHtml(action.label || "继续")}</button>`).join("")}</div>` : ""}
        ${items.length ? `<div class="agent-suggested-actions"><button class="btn" data-create-project type="button">转为学习项目</button></div>` : ""}
        <small class="run-reference">本次运行 ${escapeHtml(data.run_id || "")} · 已使用 ${Number((data.memories_used || []).length)} 条相关记忆</small>`;
      input.value = "";
      result.querySelectorAll("[data-result-go]").forEach(button => button.addEventListener("click", event => navigate(event.currentTarget.dataset.resultGo)));
      result.querySelectorAll("[data-feedback]").forEach(button => button.addEventListener("click", async () => {
        try {
          await saveFavoriteFeedback({ folder_id: Number(button.dataset.folderId), media_id: Number(button.dataset.mediaId), feedback: button.dataset.feedback, session_id: sessionId });
          button.classList.add("is-selected");
          button.parentElement.querySelectorAll("button").forEach(item => { if (item !== button) item.classList.remove("is-selected"); });
        } catch (error) { showToast(formatError(error, "反馈保存失败"), "error"); }
      }));
      result.querySelector("[data-create-project]")?.addEventListener("click", async event => {
        const goal = window.prompt("学习项目目标", command) || "";
        if (!goal.trim()) return;
        try {
          setButtonBusy(event.currentTarget, true, "创建中…");
          await createLearningProject(goal.trim(), 4, 180, items, sessionId);
          navigate("learning");
        } catch (error) { showToast(formatError(error, "学习项目创建失败"), "error"); setButtonBusy(event.currentTarget, false); }
      });
    } catch (error) {
      showInlineMessage(result, formatError(error, "Agent 暂时无法完成这个任务"));
    } finally {
      setButtonBusy(submit, false);
    }
  });

  loadWorkspace(container, navigate);
}

function renderCommandAnswer(title, evidence, action, destination) {
  return `<div class="agent-response-head"><span class="eyebrow">执行结果</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(evidence)}</p><button class="btn btn-secondary" type="button" data-result-go="${escapeAttr(destination)}">${escapeHtml(action)}</button></div>`;
}

async function loadWorkspace(container, navigate) {
  const work = container.querySelector("#currentWork");
  const insights = container.querySelector("#workspaceInsights");
  const today = container.querySelector("#todayActions");
  const progress = container.querySelector("#projectProgress");
  const pending = container.querySelector("#pendingReviews");
  try {
    const [dashboard, projectsData, structuresData, organizationsData, suggestionsData] = await Promise.all([
      getKnowledgeDashboard(), getLearningProjects(), getFolderStructurePlans(), getOrganizationPlans(), getAgentSuggestions(),
    ]);
    const projects = projectsData.projects || [];
    const structures = structuresData.plans || [];
    const organizations = organizationsData.plans || [];
    const activeProject = projects.find(item => item.status === "active") || projects[0];
    const pendingItems = [
      ...structures.filter(item => item.status === "draft").map(item => ({ type: "结构蓝图", title: item.goal, count: item.action_count })),
      ...organizations.filter(item => item.status === "draft").map(item => ({ type: "安全计划", title: item.goal, count: item.action_count })),
    ];

    work.innerHTML = [
      activeProject ? workItem("学习项目", activeProject.goal, `第 ${Number(activeProject.current_week || 1)} 周`, "learning") : "",
      pendingItems[0] ? workItem(pendingItems[0].type, pendingItems[0].title, `${Number(pendingItems[0].count || 0)} 项待审`, "operations") : "",
    ].join("") || `<div class="empty-state">当前没有进行中的任务，可以从上方给 Agent 一个目标。</div>`;
    work.querySelectorAll("[data-work-go]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.workGo)));

    insights.innerHTML = `
      <div><strong>${Number(dashboard.total || 0)}</strong><span>收藏条目</span></div>
      <div><strong>${Number(dashboard.folders_count || 0)}</strong><span>收藏夹</span></div>
      <div><strong>${Number(dashboard.indexed || 0)}</strong><span>语义索引</span></div>
      <div><strong>${Number(dashboard.health_score || 0)}</strong><span>健康度</span></div>`;
    const suggestions = suggestionsData.suggestions || [];
    today.innerHTML = suggestions.length
      ? `<div class="proactive-list">${suggestions.slice(0, 4).map(item => `<div class="proactive-item"><button data-suggestion-open="${escapeAttr(item.kind)}" type="button"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.body || "")}</span></button><button class="icon-button" data-suggestion-dismiss="${escapeAttr(item.id)}" type="button" title="忽略建议" aria-label="忽略建议">×</button></div>`).join("")}</div>`
      : `<ol class="action-list">${(dashboard.today_actions || []).slice(0, 3).map(item => `<li>${escapeHtml(item)}</li>`).join("") || `<li>完成一次同步，让 Agent 读取最新收藏。</li>`}</ol>`;
    today.querySelectorAll("[data-suggestion-open]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.suggestionOpen === "cleanup" ? "operations" : button.dataset.suggestionOpen === "interest_change" ? "profile" : "learning")));
    today.querySelectorAll("[data-suggestion-dismiss]").forEach(button => button.addEventListener("click", async () => {
      await updateAgentSuggestion(button.dataset.suggestionDismiss, "dismissed");
      button.closest(".proactive-item")?.remove();
    }));
    progress.innerHTML = activeProject
      ? `<button class="context-link" data-project-open type="button"><strong>${escapeHtml(activeProject.goal)}</strong><span>第 ${Number(activeProject.current_week || 1)} 周 · ${Number(activeProject.weekly_minutes || 0)} 分钟/周</span></button>`
      : `<p class="empty-state">还没有持续学习项目。</p>`;
    progress.querySelector("[data-project-open]")?.addEventListener("click", () => navigate("learning"));
    pending.innerHTML = pendingItems.slice(0, 3).map(item => `<button class="context-link" data-review-open type="button"><strong>${escapeHtml(item.type)}</strong><span>${escapeHtml(item.title)} · ${Number(item.count || 0)} 项</span></button>`).join("") || `<p class="empty-state">没有等待确认的操作。</p>`;
    pending.querySelectorAll("[data-review-open]").forEach(button => button.addEventListener("click", () => navigate("operations")));
  } catch (error) {
    const message = escapeHtml(formatError(error, "工作台数据加载失败"));
    work.innerHTML = `<p class="inline-error">${message}</p>`;
    insights.innerHTML = `<p class="inline-error">${message}</p>`;
    today.innerHTML = `<p class="empty-state">请先确认后端与数据库已启动。</p>`;
    progress.innerHTML = "";
    pending.innerHTML = "";
  }
}

function workItem(type, title, meta, destination) {
  return `<button class="work-item" data-work-go="${escapeAttr(destination)}" type="button"><span class="work-type">${escapeHtml(type)}</span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(meta)}</small><span class="work-arrow" aria-hidden="true">→</span></button>`;
}
