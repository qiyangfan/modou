// 视图测试共用：样例报告载荷与挂载点。
import type { ReportPayload } from "../src/types";

export function mount(): HTMLElement {
  const root = document.createElement("main");
  document.body.appendChild(root);
  return root;
}

export const verifyPayload: ReportPayload = {
  id: "r1",
  kind: "verify",
  version: 1,
  source: "verify.json",
  data: {
    report_version: 1,
    exit_code: 1,
    summary: {
      missing_execution: 1,
      wrong_execution: 0,
      historical_drift: 0,
      databases_with_findings: 1,
    },
    env_errors: [],
    databases: {
      shop: [
        {
          object_type: "table",
          object_name: "orders",
          kind: "missing_execution",
          dimensions: ["indexes"],
          details: [
            {
              dimension: "indexes",
              path: "idx_user_amount",
              expected: "exists",
              actual: "<missing>",
            },
          ],
        },
      ],
    },
  },
};

export const optimizePayload: ReportPayload = {
  id: "r2",
  kind: "optimize",
  version: 1,
  source: "optimize.json",
  data: {
    databases: {
      shop: {
        statements: [
          {
            index: 1,
            database: "shop",
            sql: "SELECT * FROM orders WHERE user_id = 42",
            baseline: {
              cost: 100.5,
              tables: [{ table: "orders", rows: 1000, access_type: "ALL" }],
              actual_time_ms: null,
            },
            findings: [{ code: "NO_WHERE", message: "x" }],
            suggestions: [
              {
                source: "rule",
                kind: "index",
                content:
                  "ALTER TABLE `shop`.`orders` ADD INDEX `idx_user_id` (`user_id`)",
                status: "measured",
                cost_before: 100.5,
                cost_after: 12.3,
                improvement_pct: 87.8,
                rows_before: [
                  { table: "orders", rows: 1000, access_type: "ALL" },
                ],
                rows_after: [{ table: "orders", rows: 12, access_type: "ref" }],
                actual_time_before_ms: null,
                actual_time_after_ms: null,
                reason: null,
                side_effects: [
                  { kind: "WRITE_AMPLIFICATION", message: "写放大提示" },
                ],
              },
              {
                source: "ai",
                kind: "index",
                content:
                  "ALTER TABLE `shop`.`orders` ADD INDEX `idx_status` (`status`)",
                status: "unverified",
                cost_before: 100.5,
                cost_after: 100.5,
                improvement_pct: null,
                rows_before: [
                  { table: "orders", rows: 1000, access_type: "ALL" },
                ],
                rows_after: [],
                actual_time_before_ms: null,
                actual_time_after_ms: null,
                reason: "代价未降低（复测代价不低于基线）",
                side_effects: [],
              },
            ],
          },
        ],
      },
    },
    evidence_env: {
      note: "采样口径声明",
      tables: [
        {
          database: "shop",
          table: "orders",
          sampled_rows: 500,
          estimated_rows: 2000,
        },
      ],
    },
    advisor: { configured: false },
  },
};

export const lintPayload: ReportPayload = {
  id: "r3",
  kind: "lint",
  version: 1,
  source: "lint.json",
  data: {
    summary: { hits: 1, error: 1, warning: 0, info: 0, files: 1 },
    hits: [
      {
        rule_id: "CLA.015",
        level: "error",
        file: "V01.sql",
        line: 3,
        message: "UPDATE 语句无 WHERE 条件，将更新全表",
        suggestion: "确认非误写",
      },
    ],
  },
};

export const driftPayload: ReportPayload = {
  id: "r4",
  kind: "patrol_drift",
  version: 1,
  source: "drift.json",
  data: {
    databases: {
      shop: [
        {
          object_type: "table",
          object_name: "orders",
          category: "added",
          dimensions: ["indexes"],
          details: [
            { path: "idx_new", expected: "<missing>", actual: "exists" },
          ],
        },
      ],
    },
  },
};

export const unusedPayload: ReportPayload = {
  id: "r5",
  kind: "patrol_unused_indexes",
  version: 1,
  source: "unused.json",
  data: {
    uptime_seconds: 604800,
    usages: [
      {
        database: "shop",
        table: "orders",
        index_name: "idx_dead",
        columns: ["b"],
        status: "confirmed_unused",
        count_star: 0,
        drop_statement: "ALTER TABLE `shop`.`orders` DROP INDEX `idx_dead`;",
        note: "",
      },
    ],
    redundancies: [],
  },
};

export const slowlogPayload: ReportPayload = {
  id: "r6",
  kind: "patrol_slowlog",
  version: 1,
  source: "slowlog.json",
  data: {
    entries_parsed: 2,
    top: [
      {
        fingerprint: "select * from orders where user_id = ?",
        count: 2,
        query_time_total: 4.0,
        query_time_max: 2.5,
        rows_examined_total: 300000,
        sample: "SELECT * FROM orders WHERE user_id = 42",
      },
    ],
  },
};

export const summaryPayload: ReportPayload = {
  id: "r7",
  kind: "patrol_summary",
  version: 1,
  source: "summary.json",
  data: {
    report_kind: "patrol_summary",
    report_version: 1,
    exit_code: 1,
    generated_at: "2026-10-16T00:00:00+00:00",
    inputs: { drift: "drift.json", unused: null, slowlog: "slow.log.json" },
    signals: {
      drift: {
        exit_code: 1,
        added: 1,
        removed: 0,
        changed: 2,
        objects: [
          {
            database: "shop",
            object_type: "table",
            object_name: "orders",
            category: "added",
          },
        ],
      },
      unused: {
        exit_code: 0,
        uptime_seconds: 604800,
        observe_days: 7,
        confirmed_unused: 2,
        low_use: 1,
        insufficient_data: 0,
        redundant: 1,
        items: [
          {
            database: "shop",
            table: "orders",
            index: "idx_dead",
            status: "confirmed_unused",
          },
        ],
      },
      slowlog: {
        exit_code: 0,
        entries_parsed: 42,
        fingerprints: 5,
        top: [
          {
            fingerprint: "select * from orders where user_id = ?",
            count: 9,
            query_time_total: 12.5,
            rows_examined_total: 900000,
          },
        ],
      },
    },
  },
};
