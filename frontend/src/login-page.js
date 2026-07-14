import { getHealth, getQrcode, pollQrcode, startDemoSession } from "./api.js";

export function renderLoginPage(app) {
  app.innerHTML = `
    <div class="centered-page">
      <div class="card" style="width:400px;">
        <h1>收藏夹管家</h1>
        <p class="subtitle">用 B站 App 扫码登录，自动整理收藏夹</p>
        <img id="qrImg" src="" alt="B站登录二维码" style="width:200px;height:200px;" hidden />
        <p id="statusText" class="status-pending" style="margin-top:12px;">等待扫码…</p>
        <p class="hint">请使用 B站 App 扫描二维码</p>
        <button id="demoModeButton" class="btn btn-secondary" type="button" hidden>体验演示模式</button>
      </div>
    </div>
  `;

  startQrcode();
  getHealth().then(data => {
    const button = document.getElementById("demoModeButton");
    if (data.demo_mode) button.hidden = false;
  }).catch(() => {});
  document.getElementById("demoModeButton").addEventListener("click", async event => {
    event.currentTarget.disabled = true;
    try { await startDemoSession(); location.reload(); }
    catch (error) { document.getElementById("statusText").textContent = error.message || "演示模式启动失败"; event.currentTarget.disabled = false; }
  });
}

async function startQrcode() {
  try {
    const data = await getQrcode();
    const img = document.getElementById("qrImg");
    const status = document.getElementById("statusText");
    img.src = data.image_url;
    img.hidden = false;
    pollLoop(data.qrcode_key, status);
  } catch (err) {
    document.getElementById("qrImg").hidden = true;
    document.getElementById("statusText").textContent = "网络异常，请刷新重试";
  }
}

async function pollLoop(key, statusEl) {
  const timer = setInterval(async () => {
    try {
      const data = await pollQrcode(key);
      if (data.status === "scanned") {
        statusEl.textContent = "已扫码，请在手机上确认…";
        statusEl.className = "status-scanned";
      } else if (data.status === "confirmed") {
        statusEl.textContent = "登录成功，跳转中…";
        statusEl.className = "status-confirmed";
        clearInterval(timer);
        setTimeout(() => location.reload(), 500);
      } else if (data.status === "expired") {
        statusEl.textContent = "二维码已过期，正在刷新…";
        statusEl.className = "status-expired";
        clearInterval(timer);
        setTimeout(startQrcode, 1000);
      }
    } catch (err) {
      // 网络波动不中断轮询
    }
  }, 2000);
}
