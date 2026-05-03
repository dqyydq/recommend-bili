const DUST_URL = "http://localhost:8000/api/dust";

const LABELS = {
  dust: { text: "吃灰", color: "#f43f5e" },
  light_dust: { text: "轻度吃灰", color: "#f59e0b" },
  watched: { text: "已看", color: "#22c55e" },
  fresh: { text: "新鲜", color: "#999" },
};

const ORDER = ["dust", "light_dust", "watched", "fresh"];

export async function renderDustModule(container) {
  container.innerHTML = `
    <div>
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:20px;">
        <button id="dustBtn" class="btn">开始检测</button>
        <button id="dustCancelBtn" class="btn btn-secondary" style="display:none;">取消</button>
      </div>
      <div id="dustProgressArea" style="display:none;margin-bottom:16px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
          <div id="dustProgressBar" style="flex:1;height:6px;background:#eee;border-radius:3px;overflow:hidden;">
            <div id="dustProgressFill" style="height:100%;width:0%;background:#FB7299;transition:width 0.3s;"></div>
          </div>
          <span id="dustProgressPercent" style="font-size:13px;color:#999;">0%</span>
        </div>
        <span id="dustProgressText" style="font-size:13px;color:#666;"></span>
      </div>
      <div id="dustResult"></div>
    </div>
  `;

  let abortCtrl = null;

  const btn = document.getElementById("dustBtn");
  const cancelBtn = document.getElementById("dustCancelBtn");
  const progressArea = document.getElementById("dustProgressArea");
  const progressFill = document.getElementById("dustProgressFill");
  const progressPercent = document.getElementById("dustProgressPercent");
  const progressText = document.getElementById("dustProgressText");
  const resultEl = document.getElementById("dustResult");

  btn.addEventListener("click", () => {
    resultEl.innerHTML = "";
    btn.disabled = true;
    btn.style.display = "none";
    cancelBtn.style.display = "inline-block";
    progressArea.style.display = "block";
    progressFill.style.width = "0%";
    progressPercent.textContent = "0%";
    progressText.textContent = "正在抓取收藏夹…";

    let favCount = 0;
    let histCount = 0;
    const estFav = 50;
    const estHist = 100;

    abortCtrl = new AbortController();
    const es = new EventSource(DUST_URL, { withCredentials: true });

    es.addEventListener("progress", (e) => {
      const d = JSON.parse(e.data);
      if (d.phase === "favorites") {
        favCount = d.count;
        const pct = Math.min(49, Math.round((favCount / estFav) * 49));
        progressFill.style.width = pct + "%";
        progressPercent.textContent = pct + "%";
        progressText.textContent = `已抓取 ${favCount} 条收藏…`;
      } else if (d.phase === "history") {
        histCount = d.count;
        const pct = Math.min(99, 50 + Math.round((histCount / estHist) * 49));
        progressFill.style.width = pct + "%";
        progressPercent.textContent = pct + "%";
        progressText.textContent = `已拉取 ${histCount} 条观看记录…`;
      }
    });

    es.addEventListener("result", (e) => {
      es.close();
      resetUI();
      renderDustResult(JSON.parse(e.data), resultEl);
    });

    es.addEventListener("error", (e) => {
      es.close();
      resetUI();
      let msg = "检测失败";
      try {
        if (e.data) {
          const d = JSON.parse(e.data);
          if (d.error) msg = d.error;
        }
      } catch (_) {}
      resultEl.innerHTML = `<p style="color:#f43f5e;">${msg}</p>`;
    });

    es.onerror = () => {
      es.close();
      resetUI();
      resultEl.innerHTML = `<p style="color:#f43f5e;">连接中断，请重试</p>`;
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
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;">
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
          <a href="${item.link}" target="_blank" rel="noopener">${item.title}</a>
          <span class="meta"> — ${item.upper}</span>
        </span>
        <span class="meta">收藏: ${favDate} | ${item.folder_name || ""}</span>
      </li>`;
    }
    html += `</ul></div>`;
  }

  el.innerHTML = html;
}
