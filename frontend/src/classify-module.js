import {
  createTopicAnalysis,
  getFolders,
  getLatestTopicAnalysis,
  getTopicAnalysis,
} from "./api.js";
import { escapeAttr, escapeHtml, formatError, showInlineMessage } from "./ui.js";

const STATE_LABELS = {
  active: "近期活跃",
  cooling: "正在降温",
  dormant: "已确认休眠",
  historical: "历史兴趣",
};

export async function renderClassifyModule(container) {
  container.innerHTML = `
    <div class="topic-tool">
      <div class="tool-command-row">
        <select id="topicFolder" class="input"><option value="">全部收藏夹</option></select>
        <button id="topicAnalyze" class="btn" type="button">生成主题地图</button>
      </div>
      <div id="topicStatus" class="task-status" hidden></div>
      <div id="topicResult"><p class="empty-state">主题地图会从本地收藏快照生成，并复用未变化的数据结果。</p></div>
    </div>`;

  const folder = container.querySelector("#topicFolder");
  const button = container.querySelector("#topicAnalyze");
  const status = container.querySelector("#topicStatus");
  const result = container.querySelector("#topicResult");

  try {
    const data = await getFolders();
    (data.folders || []).forEach(item => {
      const option = document.createElement("option");
      option.value = item.id || item.media_id;
      option.textContent = `${item.title} (${Number(item.media_count || 0)})`;
      folder.appendChild(option);
    });
    const latest = await getLatestTopicAnalysis();
    if (latest.analysis) renderAnalysis(latest.analysis, result);
  } catch (error) {
    showInlineMessage(result, formatError(error, "主题分析记录加载失败"));
  }

  folder.addEventListener("change", async () => {
    try {
      const latest = await getLatestTopicAnalysis(folder.value || null);
      if (latest.analysis) renderAnalysis(latest.analysis, result);
      else result.innerHTML = `<p class="empty-state">这个范围还没有主题分析。</p>`;
    } catch (error) {
      showInlineMessage(result, formatError(error, "主题分析记录加载失败"));
    }
  });

  button.addEventListener("click", async () => {
    button.disabled = true;
    status.hidden = false;
    status.textContent = "正在创建分析任务...";
    try {
      const data = await createTopicAnalysis(folder.value || null);
      await pollAnalysis(data.analysis.id, status, result);
    } catch (error) {
      showInlineMessage(result, formatError(error, "主题分析启动失败"));
    } finally {
      button.disabled = false;
    }
  });
}

async function pollAnalysis(id, status, result) {
  for (;;) {
    const data = await getTopicAnalysis(id);
    const analysis = data.analysis;
    status.textContent = analysis.message || "正在分析";
    if (analysis.status === "completed") {
      status.hidden = true;
      renderAnalysis(analysis, result);
      return;
    }
    if (analysis.status === "failed") throw new Error(analysis.error_message || "主题分析失败");
    await delay(900);
  }
}

function renderAnalysis(analysis, result) {
  const clusters = analysis.clusters || [];
  result.innerHTML = `
    <div class="topic-summary"><strong>${Number(analysis.item_count || 0)} 条收藏</strong><span>${clusters.length} 个主题 · 快照 ${escapeHtml((analysis.snapshot_version || "").slice(0, 8))}</span></div>
    <div class="topic-map" aria-label="收藏主题地图">
      ${clusters.map((cluster, index) => {
        const weight = Math.max(1, Number(cluster.item_count || 1));
        return `<button class="topic-node state-${escapeAttr(cluster.interest_state)}" style="--topic-weight:${weight}" data-topic-index="${index}" type="button"><strong>${escapeHtml(cluster.name)}</strong><span>${weight} 条</span></button>`;
      }).join("")}
    </div>
    <div class="topic-list">
      ${clusters.map(cluster => renderCluster(cluster)).join("") || `<p class="empty-state">没有可展示的主题。</p>`}
    </div>`;
  result.querySelectorAll("[data-topic-index]").forEach(button => button.addEventListener("click", () => {
    result.querySelectorAll(".topic-cluster")[Number(button.dataset.topicIndex)]?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

function renderCluster(cluster) {
  const representatives = cluster.representative_items || [];
  const creators = (cluster.upper_creators || []).map(item => `${item.name} ${item.count}`).join(" · ");
  return `<section class="topic-cluster">
    <div class="topic-cluster-head"><div><span class="eyebrow">${escapeHtml(STATE_LABELS[cluster.interest_state] || "兴趣主题")}</span><h3>${escapeHtml(cluster.name)}</h3></div><strong>${Number(cluster.item_count || 0)} 条</strong></div>
    <p>${escapeHtml(cluster.summary || "")}</p>
    ${creators ? `<small>常见 UP 主：${escapeHtml(creators)}</small>` : ""}
    <div class="topic-representatives">${representatives.map(item => `<a href="${escapeAttr(item.link || "#")}" target="_blank" rel="noopener"><span>${escapeHtml(item.title || "未命名收藏")}</span><small>${escapeHtml(item.upper || "")}</small></a>`).join("")}</div>
  </section>`;
}

function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
