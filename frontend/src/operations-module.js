import { getFolderStructurePlans, getLatestCleanupScan, getOrganizationPlans, getSyncStatus } from "./api.js";
import { renderFolderStructureAgent, renderOrganizationAgent } from "./agents-module.js";
import { renderCleanupModule } from "./cleanup-module.js";
import { escapeHtml, formatError } from "./ui.js";

export function renderOperationsModule(container) {
  container.innerHTML = `
    <div class="destination-head"><div><span class="eyebrow">可追溯操作</span><h1>操作记录</h1><p>同步、结构蓝图与修改计划都在这里审核和追踪。</p></div></div>
    <div id="operationsOverview" class="operations-layout">
      <section class="operation-section"><div class="section-heading compact"><div><span class="eyebrow">数据状态</span><h2>同步记录</h2></div></div><div id="syncOperation"><div class="skeleton-line"></div></div></section>
      <section class="operation-section"><div class="section-heading compact"><div><span class="eyebrow">只读草稿</span><h2>结构蓝图</h2></div><button class="text-button" data-open-operation="structure" type="button">新建与审核</button></div><div id="structureOperations"><div class="skeleton-line"></div></div></section>
      <section class="operation-section"><div class="section-heading compact"><div><span class="eyebrow">需确认后执行</span><h2>安全计划</h2></div><button class="text-button" data-open-operation="organization" type="button">查看详情</button></div><div id="organizationOperations"><div class="skeleton-line"></div></div></section>
      <section class="operation-section"><div class="section-heading compact"><div><span class="eyebrow">执行前再次验证</span><h2>失效收藏扫描</h2></div><button class="text-button" data-open-operation="cleanup" type="button">扫描与审核</button></div><div id="cleanupOperations"><div class="skeleton-line"></div></div></section>
    </div>
    <div id="operationDetail" hidden></div>`;
  container.querySelectorAll("[data-open-operation]").forEach(button => button.addEventListener("click", () => openDetail(container, button.dataset.openOperation)));
  loadOperations(container);
}

function openDetail(container, type) {
  const overview = container.querySelector("#operationsOverview");
  const detail = container.querySelector("#operationDetail");
  overview.hidden = true;
  detail.hidden = false;
  detail.innerHTML = `<button class="text-button back-button" id="backToOperations" type="button">← 返回操作记录</button><div id="operationAgent"></div>`;
  detail.querySelector("#backToOperations").addEventListener("click", () => { detail.hidden = true; overview.hidden = false; });
  const target = detail.querySelector("#operationAgent");
  if (type === "structure") renderFolderStructureAgent(target);
  else if (type === "cleanup") renderCleanupModule(target);
  else renderOrganizationAgent(target);
}

async function loadOperations(container) {
  try {
    const [sync, structuresData, organizationsData, cleanupData] = await Promise.all([getSyncStatus(), getFolderStructurePlans(), getOrganizationPlans(), getLatestCleanupScan()]);
    const job = sync.job;
    container.querySelector("#syncOperation").innerHTML = job
      ? operationRow(syncLabel(job.status), `已处理 ${Number(job.folders_processed || 0)}/${Number(job.folders_total || 0)} 个收藏夹`, job.status)
      : `<p class="empty-state">还没有同步记录。</p>`;
    container.querySelector("#structureOperations").innerHTML = renderPlanRows(structuresData.plans || [], "结构蓝图");
    container.querySelector("#organizationOperations").innerHTML = renderPlanRows(organizationsData.plans || [], "安全计划");
    const scan = cleanupData.scan;
    container.querySelector("#cleanupOperations").innerHTML = scan
      ? operationRow("最近一次失效扫描", `已检测 ${Number(scan.checked || 0)}/${Number(scan.total || 0)} 条 · ${Number(scan.confirmed_invalid_count || 0)} 条确定失效`, scan.status)
      : `<p class="empty-state">还没有失效扫描记录。</p>`;
  } catch (error) {
    const message = `<p class="inline-error">${escapeHtml(formatError(error, "操作记录加载失败"))}</p>`;
    container.querySelector("#syncOperation").innerHTML = message;
    container.querySelector("#structureOperations").innerHTML = message;
    container.querySelector("#organizationOperations").innerHTML = message;
    container.querySelector("#cleanupOperations").innerHTML = message;
  }
}

function renderPlanRows(plans, type) {
  return plans.slice(0, 5).map(plan => operationRow(plan.goal || type, `${Number(plan.action_count || 0)} 项 · ${formatDate(plan.updated_at || plan.created_at)}`, plan.status)).join("") || `<p class="empty-state">暂无${escapeHtml(type)}。</p>`;
}

function operationRow(title, meta, status) {
  return `<div class="operation-row"><div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(meta)}</span></div><span class="status-pill status-${escapeHtml(status || "idle")}">${escapeHtml(statusText(status))}</span></div>`;
}

function statusText(status) {
  return ({ queued: "排队中", running: "进行中", completed: "已完成", failed: "失败", draft: "待审核", approved: "已确认", reviewed: "已审核" })[status] || "未开始";
}

function syncLabel(status) { return status === "completed" ? "最近一次同步已完成" : status === "failed" ? "最近一次同步失败" : "收藏数据正在同步"; }
function formatDate(value) { if (!value) return "时间未知"; return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
