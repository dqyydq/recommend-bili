const BASE = import.meta.env.VITE_API_BASE || "/api";

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

export function startSync(force = false) {
  return request("/sync", {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function getSyncStatus() {
  return request("/sync/status");
}

export function analyzeProfile() {
  return request("/agents/profile");
}

export function getKnowledgeDashboard() {
  return request("/agents/dashboard");
}

export function rebuildSearchIndex() {
  return request("/agents/search/index", { method: "POST" });
}

export function semanticSearch(q, options = {}) {
  return request("/agents/search", {
    method: "POST",
    body: JSON.stringify({
      q,
      top_k: options.topK || 8,
      refresh: Boolean(options.refresh),
    }),
  });
}

export function buildLearningPath(goal, options = {}) {
  return request("/agents/learning-path", {
    method: "POST",
    body: JSON.stringify({
      goal,
      refresh: Boolean(options.refresh),
    }),
  });
}

export function logout() {
  return request("/auth/logout", { method: "POST" });
}
