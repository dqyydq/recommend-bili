import { getFolders } from "./api.js";

const SSE_BASE = "http://localhost:8000/api/analyze";

export async function renderClassifyModule(container) {
  container.innerHTML = `
    <div>
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:20px;">
        <select id="folderSelect" class="input" style="width:200px;">
          <option value="">全部收藏夹</option>
        </select>
        <button id="analyzeBtn" class="btn">开始整理</button>
        <button id="cancelBtn" class="btn btn-secondary" style="display:none;">取消</button>
      </div>
      <div id="progressArea" style="display:none;margin-bottom:16px;">
        <div class="bili-progress-area">
          <div class="header-row">
            <span class="icon" id="progressIcon">📂</span>
            <span id="progressPhase" style="font-size:14px;color:#333;">正在收集收藏夹…</span>
          </div>
          <div class="bar-row">
            <div class="bili-progress-bar">
              <div class="fill" id="progressFill"></div>
            </div>
            <span class="pct" id="progressPct">0%</span>
          </div>
          <div class="info-row" id="progressInfo"></div>
        </div>
      </div>
      <div id="analyzeResult"></div>
    </div>
  `;

  let abortCtrl = null;

  const folderSelect = document.getElementById("folderSelect");
  const btn = document.getElementById("analyzeBtn");
  const cancelBtn = document.getElementById("cancelBtn");
  const progressArea = document.getElementById("progressArea");
  const progressFill = document.getElementById("progressFill");
  const progressPct = document.getElementById("progressPct");
  const progressPhase = document.getElementById("progressPhase");
  const progressIcon = document.getElementById("progressIcon");
  const progressInfo = document.getElementById("progressInfo");
  const resultEl = document.getElementById("analyzeResult");

  // 加载收藏夹列表
  let folderList = [];
  let estimatedTotal = 50;
  try {
    const data = await getFolders();
    if (data.folders) {
      folderList = data.folders;
      for (const f of data.folders) {
        const opt = document.createElement("option");
        opt.value = f.id || f.media_id || "";
        opt.textContent = f.title || "收藏夹";
        folderSelect.appendChild(opt);
      }
    }
  } catch (e) {}

  folderSelect.addEventListener("change", () => {
    const fid = folderSelect.value;
    if (fid) {
      const f = folderList.find(x => (x.id || x.media_id) == fid);
      estimatedTotal = f ? f.media_count || 20 : 20;
    } else {
      estimatedTotal = Math.max(1, folderList.length * 20);
    }
  });

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
    progressInfo.textContent = "";

    const fid = folderSelect.value;
    const url = fid ? `${SSE_BASE}?folder_id=${fid}` : SSE_BASE;

    abortCtrl = new AbortController();
    const es = new EventSource(url, { withCredentials: true });

    es.addEventListener("progress", (e) => {
      const d = JSON.parse(e.data);
      const pct = Math.min(99, Math.round((d.total_collected / estimatedTotal) * 100));
      progressFill.style.width = pct + "%";
      progressPct.textContent = pct + "%";
      progressPhase.textContent = "正在抓取收藏夹…";
      progressIcon.textContent = "📂";
      progressInfo.textContent = `已收集 ${d.total_collected} 条（${d.folder_name} 刚完成 ${d.folder_count} 条）`;
    });

    es.addEventListener("classifying", (e) => {
      const d = JSON.parse(e.data);
      progressFill.style.width = "100%";
      progressPct.textContent = "100%";
      progressPhase.textContent = "AI 正在分析分类…";
      progressIcon.textContent = "🤖";
      progressInfo.textContent = `抓取完成，共 ${d.total} 条，正在智能命名…`;
    });

    es.addEventListener("result", (e) => {
      es.close();
      resetUI();
      const data = JSON.parse(e.data);
      renderResult(data, resultEl);
    });

    es.addEventListener("error", (e) => {
      es.close();
      resetUI();
      let msg = "请求失败";
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

    abortCtrl.signal.addEventListener("abort", () => {
      es.close();
    });
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

function renderResult(data, resultEl) {
  let html = `<p style="margin-bottom:16px;">共 ${data.total} 条收藏，分为 ${data.categories.length} 类：</p>`;
  for (const cat of data.categories) {
    html += `<div class="result-card">
      <h3>${cat.name} <span class="item-count">（${cat.items.length}）</span></h3>
      <ul class="result-list">`;
    for (const item of cat.items) {
      html += `<li>
        <a href="${item.link}" target="_blank" rel="noopener">${item.title}</a>
        <span class="meta"> — ${item.upper}</span>
      </li>`;
    }
    html += `</ul></div>`;
  }
  resultEl.innerHTML = html;
}
