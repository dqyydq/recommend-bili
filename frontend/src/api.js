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

export function setModel(model, baseUrl = null) {
  return request("/settings/model", {
    method: "POST",
    body: JSON.stringify({ model, base_url: baseUrl }),
  });
}

export function getFolders() {
  return request("/folders");
}

export function getFavorites(folderId) {
  return request(`/favorites?folder_id=${folderId}`);
}

export function getHealth() { return request("/health"); }
export function startDemoSession() { return request("/demo/session", { method: "POST" }); }
export function getAgentSuggestions() { return request("/agents/suggestions"); }
export function updateAgentSuggestion(id, status) { return request(`/agents/suggestions/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ status }) }); }
export function clearAgentMemories(confirmation) { return request("/agents/memories/clear", { method: "POST", body: JSON.stringify({ confirmation }) }); }
export function exportUserData() { return request("/data/export"); }

export function getFavoriteCover(folderId, mediaId) {
  return `${BASE}/favorites/${encodeURIComponent(folderId)}/${encodeURIComponent(mediaId)}/cover`;
}

export function createTopicAnalysis(folderId = null, force = false) {
  return request("/topics/analyses", {
    method: "POST",
    body: JSON.stringify({ folder_id: folderId ? Number(folderId) : null, force }),
  });
}

export function getTopicAnalysis(id) {
  return request(`/topics/analyses/${encodeURIComponent(id)}`);
}

export function getLatestTopicAnalysis(folderId = null) {
  const suffix = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : "";
  return request(`/topics/analyses/latest${suffix}`);
}

export function createCleanupScan(force = false) {
  return request("/clean/scans", { method: "POST", body: JSON.stringify({ force }) });
}

export function getCleanupScan(id) {
  return request(`/clean/scans/${encodeURIComponent(id)}`);
}

export function getLatestCleanupScan() {
  return request("/clean/scans/latest");
}

export function executeCleanupScan(id, items) {
  return request(`/clean/scans/${encodeURIComponent(id)}/execute`, {
    method: "POST",
    body: JSON.stringify({ items }),
  });
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

export function getAgentMemories(includeOutdated = true) {
  return request(`/agents/memories?include_outdated=${includeOutdated ? "true" : "false"}`);
}

export function createAgentMemory(payload) {
  return request("/agents/memories", { method: "POST", body: JSON.stringify(payload) });
}

export function updateAgentMemory(id, payload) {
  return request(`/agents/memories/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function outdateAgentMemory(id) {
  return request(`/agents/memories/${encodeURIComponent(id)}/outdate`, { method: "POST" });
}

export function restoreAgentMemory(id) {
  return request(`/agents/memories/${encodeURIComponent(id)}/restore`, { method: "POST" });
}

export function deleteAgentMemory(id) {
  return request(`/agents/memories/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function saveFavoriteFeedback(payload) {
  return request("/agents/feedback", { method: "POST", body: JSON.stringify(payload) });
}

export function chatWithAgent(message, sessionId = null, projectId = null) {
  return request("/agents/chat", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId, project_id: projectId }),
  });
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

export function getLearningProjects() { return request("/agents/learning-projects"); }
export function getLearningProject(id) { return request(`/agents/learning-projects/${encodeURIComponent(id)}`); }
export function createLearningProject(goal, durationWeeks, weeklyMinutes, favoriteRefs = [], sourceSessionId = null) {
  return request("/agents/learning-projects", { method: "POST", body: JSON.stringify({ goal, duration_weeks: durationWeeks, weekly_minutes: weeklyMinutes, favorite_refs: favoriteRefs, source_session_id: sourceSessionId }) });
}
export function archiveLearningProject(id) { return request(`/agents/learning-projects/${encodeURIComponent(id)}/archive`, { method: "POST" }); }
export function buildLearningProjectPlan(id) { return request(`/agents/learning-projects/${encodeURIComponent(id)}/plan`, { method: "POST" }); }
export function confirmLearningProjectWeek(id, week) { return request(`/agents/learning-projects/${encodeURIComponent(id)}/weeks/${week}/confirm`, { method: "POST" }); }
export function updateLearningProjectTask(id, taskId, state, note = "") { return request(`/agents/learning-projects/${encodeURIComponent(id)}/tasks/${encodeURIComponent(taskId)}`, { method: "POST", body: JSON.stringify({ state, note }) }); }
export function chatLearningProject(id, message) { return request(`/agents/learning-projects/${encodeURIComponent(id)}/chat`, { method: "POST", body: JSON.stringify({ message }) }); }
export function reviewLearningProject(id) { return request(`/agents/learning-projects/${encodeURIComponent(id)}/review`, { method: "POST" }); }
export function confirmLearningProjectReview(id, week) { return request(`/agents/learning-projects/${encodeURIComponent(id)}/reviews/${week}/confirm`, { method: "POST" }); }

export function buildOrganizationPlan(goal, maxActions = 12) {
  return request("/agents/organization-plans", {
    method: "POST",
    body: JSON.stringify({ goal, max_actions: maxActions }),
  });
}

export function getOrganizationPlans() {
  return request("/agents/organization-plans");
}

export function updateOrganizationPlanAction(planId, actionId, state) {
  return request(`/agents/organization-plans/${encodeURIComponent(planId)}/actions/${encodeURIComponent(actionId)}`, {
    method: "POST",
    body: JSON.stringify({ state }),
  });
}

export function approveOrganizationPlan(planId) {
  return request(`/agents/organization-plans/${encodeURIComponent(planId)}/approve`, { method: "POST" });
}

export function executeOrganizationPlan(planId) {
  return request(`/agents/organization-plans/${encodeURIComponent(planId)}/execute`, { method: "POST" });
}

export function buildFolderStructurePlan(goal) {
  return request("/agents/folder-structure-plans", { method: "POST", body: JSON.stringify({ goal }) });
}
export function getFolderStructurePlans() { return request("/agents/folder-structure-plans"); }
export function getFolderStructurePlan(id) { return request(`/agents/folder-structure-plans/${encodeURIComponent(id)}`); }
export function updateFolderStructureAction(planId, actionId, state) {
  return request(`/agents/folder-structure-plans/${encodeURIComponent(planId)}/actions/${encodeURIComponent(actionId)}`, { method: "POST", body: JSON.stringify({ state }) });
}
export function finalizeFolderStructurePlan(planId) {
  return request(`/agents/folder-structure-plans/${encodeURIComponent(planId)}/finalize`, { method: "POST" });
}

export function logout() {
  return request("/auth/logout", { method: "POST" });
}
