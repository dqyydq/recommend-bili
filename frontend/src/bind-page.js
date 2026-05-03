import { setApiKey } from "./api.js";

export function renderBindPage(app) {
  app.innerHTML = `
    <div class="centered-page">
      <div class="card">
        <h1>绑定 API Key</h1>
        <p class="subtitle">输入 DeepSeek API Key，用于分类命名</p>
        <div style="margin-bottom:16px;">
          <input id="keyInput" class="input" type="password" placeholder="sk-..." />
        </div>
        <p id="bindError" style="color:#f43f5e;font-size:13px;margin-bottom:12px;display:none;"></p>
        <button id="bindBtn" class="btn">确认并进入</button>
        <p class="hint">Key 仅保存在当前会话，后端重启后需重新绑定</p>
      </div>
    </div>
  `;

  document.getElementById("bindBtn").addEventListener("click", async () => {
    const key = document.getElementById("keyInput").value.trim();
    const errEl = document.getElementById("bindError");
    if (!key) {
      errEl.textContent = "请输入 API Key";
      errEl.style.display = "block";
      return;
    }
    try {
      await setApiKey(key);
      location.reload();
    } catch (e) {
      errEl.textContent = "绑定失败: " + e.message;
      errEl.style.display = "block";
    }
  });
}
