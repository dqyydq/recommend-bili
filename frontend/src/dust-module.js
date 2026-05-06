import { escapeAttr, escapeHtml, showInlineMessage } from "./ui.js";

const DUST_URL = "http://localhost:8000/api/dust";

const LABELS = {
  dust: { text: "吃灰", color: "#f43f5e" },
  light_dust: { text: "轻度吃灰", color: "#f59e0b" },
  fresh: { text: "新鲜", color: "#22c55e" },
};

const ORDER = ["dust", "light_dust", "fresh"];

export async function renderDustModule(container) {
  container.innerHTML = `
    <div>
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:20px;">
        <button id="dustBtn" class="btn">开始检测</button>
        <button id="dustCancelBtn" class="btn btn-secondary" style="display:none;">取消</button>
      </div>
      <div id="dustProgressArea" style="display:none;margin-bottom:16px;">
        <div class="bili-progress-area">
          <div class="header-row">
            <span class="icon" id="dustIcon">📂</span>
            <span id="dustPhase" style="font-size:14px;color:#333;">正在收集收藏夹…</span>
          </div>
          <div class="bar-row">
            <div class="bili-progress-bar">
              <div class="fill" id="dustProgressFill"></div>
            </div>
            <span class="pct" id="dustPct">0%</span>
          </div>
          <div class="info-row" id="dustInfo"></div>
        </div>
      </div>
      <div id="dustResult"></div>
    </div>
  `;

  let abortCtrl = null;

  const btn = document.getElementById("dustBtn");
  const cancelBtn = document.getElementById("dustCancelBtn");
  const progressArea = document.getElementById("dustProgressArea");
  const progressFill = document.getElementById("dustProgressFill");
  const progressPct = document.getElementById("dustPct");
  const progressPhase = document.getElementById("dustPhase");
  const progressIcon = document.getElementById("dustIcon");
  const progressInfo = document.getElementById("dustInfo");
  const resultEl = document.getElementById("dustResult");

  btn.addEventListener("click", () => {
    resultEl.innerHTML = "";
    btn.disabled = true;
    btn.style.display = "none";
    cancelBtn.style.display = "inline-block";
    progressArea.style.display = "block";
    progressFill.style.width = "0%";
    progressPct.textContent = "";
    progressPhase.textContent = "正在抓取收藏夹…";
    progressIcon.textContent = "📂";
    progressInfo.textContent = "小管家正在收集你的收藏数据~";

    let totalItems = 0;

    abortCtrl = new AbortController();
    const es = new EventSource(DUST_URL, { withCredentials: true });

    es.addEventListener("progress", (e) => {
      const d = JSON.parse(e.data);
      if (d.phase === "favorites") {
        totalItems = d.count;
        // 不显示假百分比，用流光动画表示进行中
        progressFill.style.width = "100%";
        progressPct.textContent = "";
        progressPhase.textContent = "正在抓取收藏夹…";
        progressIcon.textContent = "📂";
        progressInfo.textContent = `已收集 ${totalItems} 条收藏`;
      }
    });

    es.addEventListener("result", (e) => {
      es.close();
      progressFill.style.width = "100%";
      progressPct.textContent = "✓";
      progressPhase.textContent = "";
      progressIcon.textContent = "🎉";
      progressIcon.style.animation = "bili-pop 0.5s ease-out";
      progressInfo.textContent = `收集完成，共 ${totalItems} 条。正在分析…`;
      setTimeout(() => {
        resetUI();
        renderDustResult(JSON.parse(e.data), resultEl);
      }, 600);
    });

    es.addEventListener("error", (e) => {
      es.close();
      resetUI();
      progressArea.style.display = "none";
      let msg = "检测失败";
      try {
        if (e.data) {
          const d = JSON.parse(e.data);
          if (d.error) msg = d.error;
        }
      } catch (_) {}
      showInlineMessage(resultEl, msg);
    });

    es.onerror = () => {
      es.close();
      resetUI();
      progressArea.style.display = "none";
      showInlineMessage(resultEl, "连接中断，请重试");
    };

    abortCtrl.signal.addEventListener("abort", () => es.close());
  });

  cancelBtn.addEventListener("click", () => {
    if (abortCtrl) abortCtrl.abort();
    resetUI();
  });

  function resetUI() {
    btn.disabled = false;
    btn.style.display = "inline-block";
    cancelBtn.style.display = "none";
  }
}

function renderDustResult(data, el) {
  const { total, dust, light_dust, watched, fresh } = data;

  const statCards = ORDER.map(key => {
    const list = data[key] || [];
    const label = LABELS[key];
    return `<div style="background:#fff;border-radius:8px;padding:14px 20px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.05);border-top:3px solid ${label.color};">
      <div style="font-size:22px;font-weight:700;color:${label.color};">${list.length}</div>
      <div style="font-size:12px;color:#999;margin-top:4px;">${label.text}</div>
    </div>`;
  }).join("");

  let html = `
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:24px;">
      ${statCards}
    </div>
    <p style="margin-bottom:12px;color:#666;">共 ${total} 条收藏</p>
  `;

  for (const key of ORDER) {
    const list = data[key] || [];
    const label = LABELS[key];
    html += `<div class="result-card" style="border-left:3px solid ${label.color};">
      <h3 style="color:${label.color};">${label.text}（${list.length}）</h3>
      <ul class="result-list">`;
    for (const item of list) {
      const favDate = item.fav_time ? new Date(item.fav_time * 1000).toLocaleDateString("zh-CN") : "";
      html += `<li style="display:flex;justify-content:space-between;align-items:center;">
        <span>
          <a href="${escapeAttr(item.link)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
          <span class="meta"> — ${escapeHtml(item.upper)}</span>
        </span>
        <span class="meta">收藏: ${escapeHtml(favDate)} | ${escapeHtml(item.folder_name || "")}</span>
      </li>`;
    }
    html += `</ul></div>`;
  }

  el.innerHTML = html;
}
