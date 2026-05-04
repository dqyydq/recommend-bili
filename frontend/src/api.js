const BASE = "http://localhost:8000/api";

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }
  return resp.json();
}

export function getQrcode() {
  return request("/auth/qrcode", { method: "POST" });
}

export function pollQrcode(key) {
  return request(`/auth/qrcode/${key}/poll`, { method: "GET" });
}

export function getMe() {
  return request("/me");
}

export function setApiKey(apiKey) {
  return request("/settings/key", {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function getSettings() {
  return request("/settings");
}

export function setModel(model) {
  return request("/settings/model", {
    method: "POST",
    body: JSON.stringify({ model }),
  });
}

export function getFolders() {
  return request("/folders");
}

export function getFavorites(folderId) {
  return request(`/favorites?folder_id=${folderId}`);
}

export function searchFavorites(q) {
  return request(`/search/favorites?q=${encodeURIComponent(q)}`);
}

export function searchAll(q, page = 1) {
  return request(`/search/all?q=${encodeURIComponent(q)}&page=${page}`);
}

export function addToFavorite(bvid, folderId) {
  return request("/favorites/add", {
    method: "POST",
    body: JSON.stringify({ bvid, folder_id: folderId }),
  });
}

export function logout() {
  return request("/auth/logout", { method: "POST" });
}
