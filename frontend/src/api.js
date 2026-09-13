const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json();
}

export const api = {
  accounts: () => get("/accounts?limit=2000"),
  transactions: (since) => get(`/transactions?${since ? `since=${since}&` : ""}limit=5000`),
  riskScores: () => get("/risk-scores?limit=5000"),
  rings: () => get("/rings?limit=100"),
  ringTrace: (rootId) => get(`/rings/${encodeURIComponent(rootId)}/trace`),
  explain: (accountId) => get(`/explain/${encodeURIComponent(accountId)}`),
  startReplay: (speed = 1) => post(`/simulate/replay?speed=${speed}`),
  timelineState: (t) => get(`/timeline-state?t=${encodeURIComponent(t)}`),
  runAdaptation: () => post("/adapt/run"),
  runPipeline: () => post("/pipeline/run").catch(() => ({ ok: true })),
};

export default api;
