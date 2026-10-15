// 报告载荷类型：与 docs/formats.md 各 report_kind 契约对应（渲染层只读，不做二次计算）

export type ReportKind =
  | "verify"
  | "optimize"
  | "lint"
  | "patrol_drift"
  | "patrol_unused_indexes"
  | "patrol_slowlog";

export interface ReportMeta {
  id: string;
  kind: ReportKind;
  version: number;
  source: string;
}

export interface ReportPayload extends ReportMeta {
  data: Record<string, unknown>;
}

export const KIND_LABELS: Record<ReportKind, string> = {
  verify: "变更验收",
  optimize: "SQL 优化",
  lint: "规则审核",
  patrol_drift: "漂移巡检",
  patrol_unused_indexes: "索引巡检",
  patrol_slowlog: "慢日志聚合",
};

export interface VerifyDetail {
  dimension: string;
  path: string;
  expected: string;
  actual: string;
}

export interface VerifyConclusion {
  object_type: string;
  object_name: string;
  kind: string;
  dimensions: string[];
  details: VerifyDetail[];
}

export interface OptimizeSuggestion {
  source: string;
  kind: string;
  content: string;
  status: "measured" | "unverified";
  cost_before: number | null;
  cost_after: number | null;
  improvement_pct: number | null;
  rows_before: { table: string; rows: number; access_type: string }[];
  rows_after: { table: string; rows: number; access_type: string }[];
  actual_time_before_ms: number | null;
  actual_time_after_ms: number | null;
  reason: string | null;
  side_effects: { kind: string; message: string }[];
}

export interface OptimizeStatement {
  index: number;
  database: string | null;
  sql: string;
  baseline: {
    cost: number | null;
    tables: { table: string; rows: number; access_type: string }[];
    actual_time_ms: number | null;
  };
  findings: { code: string; message: string }[];
  suggestions: OptimizeSuggestion[];
}

export interface LintHit {
  rule_id: string;
  level: string;
  file: string;
  line: number;
  message: string;
  suggestion: string;
}

export interface PatrolDriftConclusion {
  object_type: string;
  object_name: string;
  category: string;
  dimensions: string[];
  details: VerifyDetail[];
}

export interface PatrolUsage {
  database: string;
  table: string;
  index_name: string;
  columns: string[];
  status: string;
  count_star: number;
  daily_average: number | null;
  table_share_pct: number | null;
  drop_statement: string | null;
  note: string;
}

export interface PatrolSlowlogTop {
  fingerprint: string;
  count: number;
  query_time_total: number;
  query_time_max: number;
  rows_examined_total: number;
  sample: string;
}
