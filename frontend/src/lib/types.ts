export type RunStatus = "running" | "awaiting_input" | "complete" | "partial" | "error";

export interface DemoInfo {
  model: string | null;
  model_kind: "real" | "fake";
  llm_calls: number;
  llm_failures: number;
  last_llm_error: string | null;
  daily_quota_hint: number;
  target_url: string;
}

export interface TargetConfig {
  bugs: string[];
  faults: string[];
  known_bugs?: string[];
  known_faults?: string[];
}

export interface DemoSpec {
  id: string;
  label: string;
  text: string;
}

export interface RunSummary {
  run_id: string;
  status: RunStatus;
  created_at: number | null;
  label: string | null;
  target: TargetConfig | null;
}

export interface RunStatusBody {
  run_id: string;
  status: RunStatus;
  pending_question: string | null;
  error: string | null;
  steps: number;
  tool_calls: number;
  replans: number;
  tasks_done: number;
  tasks_total: number;
  findings: number;
  stop_reason: string | null;
}

export interface LogEntry {
  step: number;
  node: string;
  decision: string;
  reason: string;
}

export interface Task {
  id: string;
  endpoint: string;
  kind: string;
  tool: string;
  param: string | null;
  objective: string;
  request: Record<string, unknown>;
  expected_status: number[];
  status: "pending" | "in_progress" | "done" | "failed";
  outcome: "unknown" | "pass" | "defect" | "inconclusive";
  attempts: number;
  parent_id: string | null;
}

export interface Finding {
  id: string;
  key: string;
  endpoint: string;
  task_id: string;
  class: string;
  status: "confirmed" | "suspected";
  expected: string;
  actual: string;
  evidence_ids: string[];
  repro: string;
}

export interface Evidence {
  id: string;
  task_id: string;
  endpoint: string;
  tool: string;
  request: { method?: string; path?: string; query?: Record<string, unknown>; headers?: Record<string, string>; query_text?: string; [k: string]: unknown };
  response: { status?: number | null; headers?: Record<string, string>; body?: string; error?: string | null; output?: unknown; ok?: boolean };
  transient_retries: number;
}

export interface RunDetails {
  run_id: string;
  base_url: string | null;
  tasks: Task[];
  findings: Finding[];
  unsupported: Finding[];
  evidence: Evidence[];
  stats: Record<string, number>;
  clarifications: { task_id: string | null; question: string; answer: string }[];
}
