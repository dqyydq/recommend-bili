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

  const contentType = resp.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await resp.json().catch(() => ({}))
    : await resp.text();

  if (!resp.ok) {
    const detail = typeof payload === "string"
      ? payload
      : payload.error || payload.detail || payload.message;
    throw new Error(detail || `HTTP ${resp.status}`);
  }

  if (payload && typeof payload === "object" && payload.error) {
    throw new Error(payload.error);
  }
  return payload;
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
