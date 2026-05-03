import { getMe } from "./api.js";
import { renderLoginPage } from "./login-page.js";
import { renderBindPage } from "./bind-page.js";
import { renderConsole } from "./console-page.js";

async function boot() {
  const app = document.getElementById("app");

  // 检查登录状态
  let user;
  try {
    user = await getMe();
  } catch (e) {
    user = { logged_in: false };
  }

  if (!user.logged_in) {
    renderLoginPage(app);
  } else if (!user.has_key) {
    renderBindPage(app);
  } else {
    renderConsole(app, user);
  }
}

boot();
