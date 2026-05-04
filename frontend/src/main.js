import { getMe } from "./api.js";
import { renderLoginPage } from "./login-page.js";
import { renderConsole } from "./console-page.js";

async function boot() {
  const app = document.getElementById("app");

  let user;
  try {
    user = await getMe();
  } catch (e) {
    user = { logged_in: false };
  }

  if (!user.logged_in) {
    renderLoginPage(app);
  } else {
    renderConsole(app, user);
  }
}

boot();
