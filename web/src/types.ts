export type StatusKind = "agent" | "action" | "human" | "done";

export interface Status {
  id: string;
  name: string;
  kind: StatusKind;
  agent_id?: string | null;
  action?: string | null;
  x: number;
  y: number;
}

export interface Transition {
  id: string;
  source: string;
  outcome: string;
  target: string;
  effects: string[];
}

export interface Rule {
  id: string;
  type: "max_visits" | "max_errors";
  status: string | null;
  limit: number;
  target: string;
}

export interface Workflow {
  id: string;
  name: string;
  version: number;
  statuses: Status[];
  transitions: Transition[];
  rules: Rule[];
  fallback_status: string;
}

export interface Outcome {
  name: string;
  description: string;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  model: string | null;
  effort: string | null;
  tools: string[];
  permission_mode: string;
  max_turns: number | null;
  workspace: "write" | "read" | "none";
  outcomes: Outcome[];
  post_checks: string[];
  blocked_commands: string[];
  include_diff: boolean;
}

export interface Project {
  id: string;
  name: string;
  repo: string;
  board_owner: string;
  board_number: number;
  local_path: string;
  base_branch: string;
  setup_command: string;
  test_command: string;
  workflow_id: string;
  context: string;
  enabled: boolean;
}

export interface LogEntry {
  t: number;
  type: string;
  text?: string;
  name?: string;
  input?: string;
  [k: string]: unknown;
}

export interface Run {
  id: string;
  project_id: string;
  item_id: string;
  issue_number: number | null;
  status_id: string;
  worker: string;
  started_at: number;
  finished_at: number | null;
  outcome: string | null;
  target_status_id: string | null;
  summary: string;
  error: string | null;
  cost_usd: number | null;
  num_turns: number | null;
  log: LogEntry[];
}

export interface WorkerState {
  paused: boolean;
  paused_until: number | null;
  current: { run_id: string; project: string; card: string; issue: number; status: string; worker: string; started_at: number; log: LogEntry[] } | null;
  warnings: string[];
  last_tick: number | null;
  last_error: string | null;
  api_key_in_env: boolean;
}

export interface Catalog {
  actions: Record<string, { description: string; outcomes: Record<string, string> }>;
  effects: Record<string, string>;
  post_checks: Record<string, string>;
  tools: string[];
}
