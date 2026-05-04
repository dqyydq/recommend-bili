const BASE = "http://localhost:8000/api";
const ANALYZE_URL = `${BASE}/analyze`;
const SCAN_URL = `${BASE}/clean/scan`;
const REMOVE_URL = `${BASE}/clean/remove`;
const SAVE_URL = `${BASE}/classify/save`;
const HISTORY_URL = `${BASE}/classify/history`;
const LOAD_URL = `${BASE}/classify/load`;

export async function renderOrganizeModule(container) {
  container.innerHTML = `
    <div>
      <div class="tabs">
        <div class="tab active" data-tab="clean">清除失效</div>
        <div class="tab" data-tab="reclassify">重新分类</div>
        <div class="tab" data-tab="history">分类历史</div>
      </div>
      <div id="orgContent" style="margin-top:16px;"></div>
    </div>
  `;

  const content = document.getElementById("orgContent");
  const tabs = document.querySelectorAll(".tab");

  tabs.forEach(t => t.addEventListener("click", () => {
    tabs.forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    renderTab(t.dataset.tab, content);
  }));

  renderTab("clean", content);
}

let _activeES = null;
function trackES(es) { _activeES = es; }
function untrackES() { _activeES = null; }

function renderTab(name, content) {
  if (_activeES) { _activeES.close(); _activeES = null; }
  content.innerHTML = "";
  classifyData = null;
  if (name === "clean") renderCleanTab(content);
  if (name === "reclassify") renderReclassifyTab(content);
  if (name === "history") renderHistoryTab(content);
}

/* ========== Tab 1: 清除失效 ========== */

function renderCleanTab(el) {
  el.innerHTML = `
    <button id="cleanScanBtn" class="btn">扫描失效视频</button>
    <span id="cleanStatus" style="font-size:13px;color:#999;margin-left:10px;"></span>
    <div id="cleanProgress" style="display:none;margin-top:12px;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
        <div style="flex:1;height:6px;background:#eee;border-radius:3px;overflow:hidden;">
          <div id="cleanProgressFill" style="height:100%;width:0%;background:#FB7299;transition:width 0.3s;"></div>
        </div>
        <span id="cleanProgressText" style="font-size:12px;color:#999;"></span>
      </div>
    </div>
    <div id="cleanResult" style="margin-top:16px;"></div>
  `;

  document.getElementById("cleanScanBtn").addEventListener("click", () => {
    const btn = document.getElementById("cleanScanBtn");
    const status = document.getElementById("cleanStatus");
    btn.disabled = true;
    status.textContent = "收集收藏夹…";
    const progressDiv = document.getElementById("cleanProgress");
    const progressFill = document.getElementById("cleanProgressFill");
    const progressText = document.getElementById("cleanProgressText");
    progressDiv.style.display = "block";

    const es = new EventSource(SCAN_URL, { withCredentials: true });
    trackES(es);
    let invalidItems = [];

    es.addEventListener("progress", (e) => {
      const d = JSON.parse(e.data);
      const pct = Math.round((d.checked / d.total) * 100);
      progressFill.style.width = pct + "%";
      progressText.textContent = `${d.checked}/${d.total}`;
      status.textContent = `验证中… 已发现 ${d.invalid} 个失效`;
    });

    es.addEventListener("result", (e) => {
      es.close();
      btn.disabled = false;
      const d = JSON.parse(e.data);
      invalidItems = d.invalid || [];
      status.textContent = `发现 ${invalidItems.length} 个失效视频`;
      renderCleanList(invalidItems, document.getElementById("cleanResult"));
    });

    es.addEventListener("error", () => { es.close(); btn.disabled = false; status.textContent = "扫描失败"; });
    es.onerror = () => { es.close(); btn.disabled = false; status.textContent = "连接中断"; };
  });
}

function renderCleanList(items, el) {
  if (items.length === 0) {
    el.innerHTML = `<p style="color:#22c55e;">未发现失效视频</p>`;
    return;
  }
  let html = `<div style="margin-bottom:12px;display:flex;gap:8px;">
    <button id="selectAllBtn" class="btn btn-secondary">全选</button>
    <button id="removeBtn" class="btn" style="background:#f43f5e;">确认移除选中</button>
  </div>`;
  for (const item of items) {
    html += `<label class="result-card" style="display:flex;align-items:center;gap:10px;cursor:pointer;">
      <input type="checkbox" class="clean-cb" data-bvid="${item.bvid}" data-fid="${item.folder_id || ''}" data-mid="${item.id || 0}" style="width:16px;height:16px;" />
      <div>
        <a href="${item.link}" target="_blank">${item.title}</a>
        <span class="meta"> — ${item.upper} | ${item.folder_name}</span>
      </div>
    </label>`;
  }
  el.innerHTML = html;

  document.getElementById("selectAllBtn").addEventListener("click", () => {
    const all = el.querySelectorAll(".clean-cb");
    const checked = [...all].some(c => c.checked);
    all.forEach(c => { c.checked = !checked; });
  });

  document.getElementById("removeBtn").addEventListener("click", async () => {
    const cbs = el.querySelectorAll(".clean-cb:checked");
    const items = [...cbs].map(c => ({ bvid: c.dataset.bvid, folder_id: parseInt(c.dataset.fid) || 0, media_id: parseInt(c.dataset.mid) || 0 }));
    if (!items.length) return alert("请勾选要移除的视频");
    if (!confirm(`确认移除 ${items.length} 个失效视频？`)) return;

    const resp = await fetch(REMOVE_URL, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    el.innerHTML = `<p style="color:#22c55e;">已移除 ${data.removed}/${data.total} 个视频</p>`;
  });
}

/* ========== Tab 2: 重新分类 ========== */

let classifyData = null;

function renderReclassifyTab(el) {
  el.innerHTML = `
    <button id="reclassifyBtn" class="btn">开始重新分类</button>
    <div id="reclassifyProgress" style="display:none;margin-top:12px;"></div>
    <div id="reclassifyResult" style="margin-top:16px;"></div>
    <div id="reclassifyActions" style="display:none;margin-top:12px;">
      <button id="saveClassifyBtn" class="btn">确认保存</button>
      <span id="saveStatus" style="font-size:13px;color:#999;margin-left:10px;"></span>
    </div>
  `;

  document.getElementById("reclassifyBtn").addEventListener("click", () => {
    const btn = document.getElementById("reclassifyBtn");
    const progress = document.getElementById("reclassifyProgress");
    btn.disabled = true;
    progress.style.display = "block";
    progress.innerHTML = `<span style="color:#999;">正在抓取和分析…</span>`;

    const es = new EventSource(ANALYZE_URL, { withCredentials: true });
    trackES(es);

    es.addEventListener("progress", (e) => {
      const d = JSON.parse(e.data);
      progress.innerHTML = `<span style="color:#666;">已抓取 ${d.total_collected} 条</span>`;
    });

    es.addEventListener("classifying", () => {
      progress.innerHTML = `<span style="color:#666;">正在 AI 分析…</span>`;
    });

    es.addEventListener("result", (e) => {
      es.close();
      btn.disabled = false;
      progress.style.display = "none";
      classifyData = JSON.parse(e.data);
      document.getElementById("reclassifyActions").style.display = "block";
      renderEditableResult(classifyData, document.getElementById("reclassifyResult"));
    });

    es.addEventListener("error", (e) => {
      es.close(); btn.disabled = false;
      progress.innerHTML = `<span style="color:#f43f5e;">分析失败</span>`;
    });
    es.onerror = () => { es.close(); btn.disabled = false; };
  });

  document.getElementById("saveClassifyBtn").addEventListener("click", async () => {
    const status = document.getElementById("saveStatus");
    status.textContent = "保存中…";
    const resp = await fetch(SAVE_URL, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_name: "全部收藏夹", categories: classifyData.categories }),
    });
    const d = await resp.json();
    status.textContent = d.success ? `已保存 (${d.filename})` : `失败: ${d.error}`;
  });
}

function renderEditableResult(data, el) {
  let html = `<p style="margin-bottom:12px;">共 ${data.total} 条，${data.categories.length} 个分类（拖拽视频可移动，点击分类名可编辑）</p>`;
  data.categories.forEach((cat, ci) => {
    html += `<div class="result-card cat-card" data-ci="${ci}" style="border-left:3px solid #FB7299;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <h3 class="cat-name" data-ci="${ci}" style="cursor:pointer;margin:0;" title="点击编辑名称">${cat.name} <span class="item-count">（${cat.items.length}）</span></h3>
        <div style="display:flex;gap:6px;">
          <select class="merge-select" data-ci="${ci}" style="font-size:12px;padding:2px 4px;">
            <option value="">合并到…</option>
            ${data.categories.map((c, i) => i !== ci ? `<option value="${i}">${c.name}</option>` : "").join("")}
          </select>
          <button class="btn btn-secondary del-cat-btn" data-ci="${ci}" style="font-size:12px;padding:2px 8px;">×</button>
        </div>
      </div>
      <ul class="result-list cat-items" data-ci="${ci}">`;
    cat.items.forEach((item, ii) => {
      html += `<li draggable="true" class="drag-item" data-ci="${ci}" data-ii="${ii}" style="cursor:grab;padding:6px 0;border-bottom:1px solid #f5f5f5;">
        <a href="${item.link}" target="_blank">${item.title}</a>
        <span class="meta"> — ${item.upper}</span>
      </li>`;
    });
    html += `</ul></div>`;
  });
  el.innerHTML = html;

  // rename category
  el.querySelectorAll(".cat-name").forEach(h3 => {
    h3.addEventListener("dblclick", () => {
      const ci = parseInt(h3.dataset.ci);
      const input = document.createElement("input");
      input.value = classifyData.categories[ci].name;
      input.style.cssText = "font-size:16px;font-weight:600;border:1px solid #FB7299;border-radius:4px;padding:2px 6px;width:200px;";
      h3.replaceWith(input);
      input.focus();
      input.select();
      input.addEventListener("blur", () => {
        classifyData.categories[ci].name = input.value || classifyData.categories[ci].name;
        renderEditableResult(classifyData, el);
      });
      input.addEventListener("keydown", e => { if (e.key === "Enter") input.blur(); });
    });
  });

  // delete category
  el.querySelectorAll(".del-cat-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const ci = parseInt(btn.dataset.ci);
      const cat = classifyData.categories[ci];
      classifyData.categories.splice(ci, 1);
      // add orphaned items to "未分类"
      let uncat = classifyData.categories.find(c => c.name === "未分类");
      if (!uncat) { uncat = { name: "未分类", items: [] }; classifyData.categories.push(uncat); }
      uncat.items.push(...cat.items);
      renderEditableResult(classifyData, el);
    });
  });

  // merge category
  el.querySelectorAll(".merge-select").forEach(sel => {
    sel.addEventListener("change", () => {
      const fromCi = parseInt(sel.dataset.ci);
      const toCi = parseInt(sel.value);
      if (isNaN(toCi)) return;
      classifyData.categories[toCi].items.push(...classifyData.categories[fromCi].items);
      classifyData.categories.splice(fromCi, 1);
      renderEditableResult(classifyData, el);
    });
  });

  // drag & drop
  el.querySelectorAll(".drag-item").forEach(item => {
    item.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", JSON.stringify({ ci: item.dataset.ci, ii: item.dataset.ii }));
      item.style.opacity = "0.5";
    });
    item.addEventListener("dragend", () => { item.style.opacity = "1"; });
  });

  el.querySelectorAll(".cat-items").forEach(ul => {
    ul.addEventListener("dragover", e => { e.preventDefault(); ul.style.background = "#fdf2f5"; });
    ul.addEventListener("dragleave", () => { ul.style.background = ""; });
    ul.addEventListener("drop", (e) => {
      e.preventDefault();
      ul.style.background = "";
      const { ci: fromCi, ii } = JSON.parse(e.dataTransfer.getData("text/plain"));
      const toCi = parseInt(ul.dataset.ci);
      if (fromCi === toCi) return;
      const [moved] = classifyData.categories[fromCi].items.splice(parseInt(ii), 1);
      classifyData.categories[toCi].items.push(moved);
      renderEditableResult(classifyData, el);
    });
  });
}

/* ========== Tab 3: 分类历史 ========== */

async function renderHistoryTab(el) {
  el.innerHTML = `<p style="color:#999;">加载中…</p>`;
  try {
    const resp = await fetch(HISTORY_URL, { credentials: "include" });
    const data = await resp.json();
    if (data.history.length === 0) {
      el.innerHTML = `<p style="color:#999;">暂无保存的分类记录</p>`;
      return;
    }
    let html = `<ul class="result-list">`;
    for (const h of data.history) {
      html += `<li style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" class="history-item" data-file="${h.filename}">
        <span>${h.created_at} — ${h.total} 条 / ${h.categories_count} 类</span>
        <button class="btn btn-secondary" style="font-size:12px;padding:4px 10px;">查看</button>
      </li>`;
    }
    html += `</ul><div id="historyDetail" style="margin-top:16px;"></div>`;
    el.innerHTML = html;

    el.querySelectorAll(".history-item").forEach(li => {
      li.addEventListener("click", async () => {
        const detailEl = document.getElementById("historyDetail");
        detailEl.innerHTML = `<p style="color:#999;">加载中…</p>`;
        const resp = await fetch(`${LOAD_URL}?file=${li.dataset.file}`, { credentials: "include" });
        const data = await resp.json();
        if (data.error) { detailEl.innerHTML = `<p style="color:#f43f5e;">${data.error}</p>`; return; }
        let dhtml = `<p style="margin-bottom:12px;">共 ${data.total} 条，${data.categories.length} 类</p>`;
        for (const cat of data.categories) {
          dhtml += `<div class="result-card"><h3>${cat.name}（${cat.items.length}）</h3><ul class="result-list">`;
          for (const item of cat.items) {
            dhtml += `<li><a href="${item.link}" target="_blank">${item.title}</a><span class="meta"> — ${item.upper}</span></li>`;
          }
          dhtml += `</ul></div>`;
        }
        detailEl.innerHTML = dhtml;
      });
    });
  } catch (e) {
    el.innerHTML = `<p style="color:#f43f5e;">加载失败: ${e.message}</p>`;
  }
}
