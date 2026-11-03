import type { DemoInfo, DemoSpec, LogEntry, RunDetails, RunStatusBody, RunSummary, TargetConfig } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? response.json() : response.text()) as Promise<T>;
}

export const api = {
  info: () => request<DemoInfo>("/demo/info"),
  specs: () => request<{ specs: DemoSpec[] }>("/demo/specs").then((r) => r.specs),
  architecture: () => request<string>("/demo/architecture"),
  evaluation: () => request<string>("/demo/eval"),
  target: () => request<TargetConfig>("/demo/target"),
  runs: () => request<{ runs: RunSummary[] }>("/runs").then((r) => r.runs),
  status: (id: string) => request<RunStatusBody>(`/runs/${id}`),
  trace: (id: string) => request<{ decision_log: LogEntry[] }>(`/runs/${id}/trace`).then((r) => r.decision_log),
  details: (id: string) => request<RunDetails>(`/runs/${id}/details`),
  report: (id: string) => request<string>(`/runs/${id}/report`),
  start: (body: {
    spec: string;
    base_url: string;
    label: string;
    config: Record<string, unknown>;
    target: TargetConfig;
  }) => request<{ run_id: string }>("/runs", { method: "POST", body: JSON.stringify(body) }),
  resume: (id: string, answer: string) =>
    request<{ run_id: string }>(`/runs/${id}/resume`, { method: "POST", body: JSON.stringify({ answer }) }),
};
