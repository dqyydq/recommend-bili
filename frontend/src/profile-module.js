import {
  createAgentMemory,
  deleteAgentMemory,
  getAgentMemories,
  outdateAgentMemory,
  restoreAgentMemory,
  updateAgentMemory,
} from "./api.js";
import { escapeAttr, escapeHtml, formatError, showInlineMessage } from "./ui.js";

const STATE_LABELS = { active: "当前兴趣", cooling: "正在降温", dormant: "已确认休眠", historical: "历史轨迹" };
const TYPE_LABELS = { semantic: "偏好与事实", episodic: "经历与反馈", procedural: "Agent 规则" };

export async function renderProfileModule(container) {
  container.innerHTML = `
    <div class="destination-head"><div><span class="eyebrow">透明记忆</span><h1>我的画像</h1><p>查看 Agent 记住了什么、依据是什么，并随时纠正、过时或删除。</p></div><button id="addMemoryButton" class="btn" type="button">添加明确偏好</button></div>
    <form id="memoryComposer" class="memory-composer" hidden>
      <input id="memoryContent" class="input" maxlength="1000" placeholder="例如：我更喜欢带完整项目的实战教程" required>
      <select id="memoryType" class="input"><option value="semantic">偏好与事实</option><option value="procedural">Agent 规则</option><option value="episodic">经历与反馈</option></select>
      <button class="btn" type="submit">保存</button>
    </form>
    <div id="memoryMessage"></div>
    <div id="memoryTimeline"><div class="skeleton-line"></div></div>`;
  const composer = container.querySelector("#memoryComposer");
  container.querySelector("#addMemoryButton").addEventListener("click", () => {
    composer.hidden = !composer.hidden;
    if (!composer.hidden) container.querySelector("#memoryContent").focus();
  });
  composer.addEventListener("submit", async event => {
    event.preventDefault();
    const content = container.querySelector("#memoryContent").value.trim();
    if (!content) return;
    try {
      await createAgentMemory({ memory_type: container.querySelector("#memoryType").value, content, source_kind: "explicit", confidence: 1, interest_state: "active" });
      composer.reset();
      composer.hidden = true;
      await loadMemories(container);
    } catch (error) {
      showInlineMessage(container.querySelector("#memoryMessage"), formatError(error, "记忆保存失败"));
    }
  });
  await loadMemories(container);
}

async function loadMemories(container) {
  const timeline = container.querySelector("#memoryTimeline");
  try {
    const data = await getAgentMemories(true);
    const groups = ["active", "cooling", "dormant", "historical"];
    timeline.innerHTML = groups.map(state => renderGroup(state, (data.memories || []).filter(memory => memory.interest_state === state))).join("");
    bindMemoryActions(container);
  } catch (error) {
    showInlineMessage(timeline, formatError(error, "画像加载失败"));
  }
}

function renderGroup(state, memories) {
  return `<section class="memory-group"><div class="section-heading compact"><div><span class="eyebrow">兴趣时间线</span><h2>${escapeHtml(STATE_LABELS[state])}</h2></div><span>${memories.length} 条</span></div>
    <div class="memory-list">${memories.map(renderMemory).join("") || `<p class="empty-state">暂无${escapeHtml(STATE_LABELS[state])}记忆。</p>`}</div></section>`;
}

function renderMemory(memory) {
  const confidence = Math.round(Number(memory.effective_confidence || 0) * 100);
  const evidence = memory.evidence || [];
  return `<article class="memory-row ${memory.status === "outdated" ? "is-outdated" : ""}" data-memory-id="${escapeAttr(memory.id)}">
    <div class="memory-main"><span class="memory-type">${escapeHtml(TYPE_LABELS[memory.memory_type] || memory.memory_type)}</span><strong>${escapeHtml(memory.content)}</strong><p>${escapeHtml(memory.state_reason || "")}</p><small>有效置信度 ${confidence}% · ${memory.source_kind === "explicit" ? "你的明确表达" : "Agent 推测"}${evidence.length ? ` · ${evidence.length} 条证据` : ""}</small></div>
    <div class="memory-controls">
      <select data-memory-state class="input" aria-label="兴趣状态"><option value="active" ${memory.interest_state === "active" ? "selected" : ""}>当前</option><option value="cooling" ${memory.interest_state === "cooling" ? "selected" : ""}>降温</option><option value="dormant" ${memory.interest_state === "dormant" ? "selected" : ""}>休眠</option><option value="historical" ${memory.interest_state === "historical" ? "selected" : ""}>历史</option></select>
      <button class="text-button" data-memory-toggle type="button">${memory.status === "outdated" ? "恢复" : "标记过时"}</button>
      <button class="icon-button" data-memory-delete type="button" title="删除记忆" aria-label="删除记忆">×</button>
    </div>
  </article>`;
}

function bindMemoryActions(container) {
  container.querySelectorAll("[data-memory-state]").forEach(select => select.addEventListener("change", async () => {
    const row = select.closest("[data-memory-id]");
    try {
      await updateAgentMemory(row.dataset.memoryId, { interest_state: select.value, confirm_as_explicit: select.value === "dormant" });
      await loadMemories(container);
    } catch (error) {
      showInlineMessage(container.querySelector("#memoryMessage"), formatError(error, "状态更新失败"));
    }
  }));
  container.querySelectorAll("[data-memory-toggle]").forEach(button => button.addEventListener("click", async () => {
    const row = button.closest("[data-memory-id]");
    try {
      row.classList.contains("is-outdated") ? await restoreAgentMemory(row.dataset.memoryId) : await outdateAgentMemory(row.dataset.memoryId);
      await loadMemories(container);
    } catch (error) { showInlineMessage(container.querySelector("#memoryMessage"), formatError(error, "记忆更新失败")); }
  }));
  container.querySelectorAll("[data-memory-delete]").forEach(button => button.addEventListener("click", async () => {
    const row = button.closest("[data-memory-id]");
    if (!window.confirm("删除后，这条记忆及证据不会再参与 Agent 判断。是否继续？")) return;
    try { await deleteAgentMemory(row.dataset.memoryId); await loadMemories(container); }
    catch (error) { showInlineMessage(container.querySelector("#memoryMessage"), formatError(error, "记忆删除失败")); }
  }));
}
