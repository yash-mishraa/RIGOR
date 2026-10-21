const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers }
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Request failed");
  return payload;
}

export const rigorApi = {
  health: () => request("/health"),
  listJobs: (params = {}) => request(`/jobs?${new URLSearchParams(params)}`),
  getJob: (id) => request(`/jobs/${id}`),
  getJobSkills: (id) => request(`/jobs/${id}/skills`),
  getCoverage: (id) => request(`/jobs/${id}/content-coverage`),
  importJob: (job) => request("/jobs/import", { method: "POST", body: JSON.stringify(job) }),
  createPlan: (jobId, questionLimit = 12) => request("/preparation-plans", {
    method: "POST", body: JSON.stringify({ job_id: jobId, question_limit: questionLimit })
  })
};
