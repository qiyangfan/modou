// 组件级测试：四类视图对样例报告的渲染断言（jsdom）
import { beforeEach, describe, expect, it } from "vitest";
import { renderReport } from "../src/views";
import type { ReportPayload } from "../src/types";

function mount(): HTMLElement {
  const root = document.createElement("main");
  document.body.appendChild(root);
  return root;
}

const verifyPayload: ReportPayload = {
  id: "r1",
  kind: "verify",
  version: 1,
  source: "verify.json",
  data: {
    report_version: 1,
    exit_code: 1,
    summary: { missing_execution: 1, wrong_execution: 0, historical_drift: 0, databases_with_findings: 1 },
    env_errors: [],
    databases: {
      shop: [
        {
          object_type: "table",
          object_name: "orders",
          kind: "missing_execution",
          dimensions: ["indexes"],
          details: [{ dimension: "indexes", path: "idx_user_amount", expected: "exists", actual: "<missing>" }],
        },
      ],
    },
  },
};

const optimizePayload: ReportPayload = {
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
            baseline: { cost: 100.5, tables: [{ table: "orders", rows: 1000, access_type: "ALL" }], actual_time_ms: null },
            findings: [{ code: "NO_WHERE", message: "x" }],
            suggestions: [
              {
                source: "rule",
                kind: "index",
                content: "ALTER TABLE `shop`.`orders` ADD INDEX `idx_user_id` (`user_id`)",
                status: "measured",
                cost_before: 100.5,
                cost_after: 12.3,
                improvement_pct: 87.8,
                rows_before: [{ table: "orders", rows: 1000, access_type: "ALL" }],
                rows_after: [{ table: "orders", rows: 12, access_type: "ref" }],
                actual_time_before_ms: null,
                actual_time_after_ms: null,
                reason: null,
                side_effects: [{ kind: "WRITE_AMPLIFICATION", message: "写放大提示" }],
              },
              {
                source: "ai",
                kind: "index",
                content: "ALTER TABLE `shop`.`orders` ADD INDEX `idx_status` (`status`)",
                status: "unverified",
                cost_before: 100.5,
                cost_after: 100.5,
                improvement_pct: null,
                rows_before: [{ table: "orders", rows: 1000, access_type: "ALL" }],
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
    evidence_env: { note: "采样口径声明", tables: [{ database: "shop", table: "orders", sampled_rows: 500, estimated_rows: 2000 }] },
    advisor: { configured: false },
  },
};

const lintPayload: ReportPayload = {
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

const driftPayload: ReportPayload = {
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
          details: [{ path: "idx_new", expected: "<missing>", actual: "exists" }],
        },
      ],
    },
  },
};

const unusedPayload: ReportPayload = {
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

const slowlogPayload: ReportPayload = {
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

describe("report views", () => {
  beforeEach(() => {
    document.body.replaceChildren();
  });

  it("verify view renders conclusions grouped by db", () => {
    const root = mount();
    renderReport(root, verifyPayload);
    expect(root.textContent).toContain("变更验收");
    expect(root.textContent).toContain("库 shop");
    expect(root.textContent).toContain("漏执行");
    expect(root.textContent).toContain("idx_user_amount");
  });

  it("optimize view renders two-state suggestions only", () => {
    const root = mount();
    renderReport(root, optimizePayload);
    const text = root.textContent ?? "";
    expect(text).toContain("实测提升 87.8%");
    expect(text).toContain("未验证");
    expect(text).toContain("代价未降低");
    expect(text).toContain("采样口径声明");
  });

  it("lint view renders hits table", () => {
    const root = mount();
    renderReport(root, lintPayload);
    expect(root.textContent).toContain("CLA.015");
    expect(root.textContent).toContain("V01.sql:3");
  });

  it("patrol drift view renders categories", () => {
    const root = mount();
    renderReport(root, driftPayload);
    expect(root.textContent).toContain("新增");
    expect(root.textContent).toContain("orders");
  });

  it("patrol unused view renders layered status and drop statement", () => {
    const root = mount();
    renderReport(root, unusedPayload);
    expect(root.textContent).toContain("确认未用");
    expect(root.textContent).toContain("DROP INDEX `idx_dead`");
  });

  it("patrol slowlog view renders fingerprint ranking", () => {
    const root = mount();
    renderReport(root, slowlogPayload);
    expect(root.textContent).toContain("次数 2");
    expect(root.textContent).toContain("user_id = ?");
  });
});


describe("review regressions", () => {
  beforeEach(() => {
    document.body.replaceChildren();
  });

  it("exit-2 verify with empty databases never claims 全部一致", () => {
    const root = mount();
    renderReport(root, {
      id: "v2",
      kind: "verify",
      version: 1,
      source: "v2.json",
      data: {
        report_version: 1,
        exit_code: 2,
        summary: { missing_execution: 0, wrong_execution: 0, historical_drift: 0 },
        env_errors: ["shadow container failed: image not found"],
        databases: {},
      },
    });
    const text = root.textContent ?? "";
    expect(text).toContain("环境/输入错误");
    expect(text).not.toContain("全部一致");
  });

  it("clean empty verify still claims 全部一致", () => {
    const root = mount();
    renderReport(root, {
      id: "v3",
      kind: "verify",
      version: 1,
      source: "v3.json",
      data: {
        report_version: 1,
        exit_code: 0,
        summary: { missing_execution: 0, wrong_execution: 0, historical_drift: 0 },
        env_errors: [],
        databases: {},
      },
    });
    expect(root.textContent).toContain("全部一致");
  });

  it("malformed payload renders error card instead of crashing", () => {
    // 各 renderer 已做 ?? 缺省；能击穿防御的只剩类型错位（数字字段给成字符串）
    const root = mount();
    renderReport(root, {
      id: "bad",
      kind: "patrol_slowlog",
      version: 1,
      source: "bad.json",
      data: {
        entries_parsed: 1,
        top: [{ count: 1, query_time_total: "oops", query_time_max: 1, rows_examined_total: 1, fingerprint: "f", sample: "s" }],
      },
    });
    expect(root.textContent).toContain("报告解析失败");
  });

  it("measured suggestion renders rows before/after", () => {
    const root = mount();
    renderReport(root, optimizePayload);
    const text = root.textContent ?? "";
    expect(text).toContain("扫描行数 前:");
    expect(text).toContain("orders=1000");
    expect(text).toContain("扫描行数 后:");
    expect(text).toContain("orders=12");
  });

  it("optimize evidence lists unsampled tables explicitly", () => {
    const root = mount();
    renderReport(root, {
      id: "opt2",
      kind: "optimize",
      version: 1,
      source: "opt2.json",
      data: {
        databases: {},
        evidence_env: {
          note: "n",
          tables: [{ database: "shop", table: "logs", sampled_rows: null, estimated_rows: null }],
        },
        advisor: { configured: false },
      },
    });
    expect(root.textContent).toContain("未采样");
  });
});


describe("round-2 review regressions", () => {
  beforeEach(() => {
    document.body.replaceChildren();
  });

  it("exit-2 optimize report renders failure reasons, not just AI-unconfigured", () => {
    const root = mount();
    renderReport(root, {
      id: "optfail",
      kind: "optimize",
      version: 1,
      source: "optfail.json",
      data: {
        exit_code: 2,
        env_errors: ["shadow container failed: image not found"],
        input_errors: [],
        databases: {},
        evidence_env: { note: "", tables: [] },
        advisor: { configured: false },
      },
    });
    const text = root.textContent ?? "";
    expect(text).toContain("环境错误");
    expect(text).toContain("shadow container failed");
    expect(text).not.toContain("AI 未配置");
  });

  it("verify with exit_code 1 and empty databases never claims 全部一致", () => {
    const root = mount();
    renderReport(root, {
      id: "v4",
      kind: "verify",
      version: 1,
      source: "v4.json",
      data: {
        report_version: 1,
        exit_code: 1,
        summary: { missing_execution: 0, wrong_execution: 0, historical_drift: 0 },
        env_errors: [],
        databases: {},
      },
    });
    expect(root.textContent).not.toContain("全部一致");
  });

  it("slowlog view renders skipped count", () => {
    const root = mount();
    renderReport(root, {
      id: "slow2",
      kind: "patrol_slowlog",
      version: 1,
      source: "slow2.json",
      data: { entries_parsed: 3, skipped_lines: 2, top: [] },
    });
    expect(root.textContent).toContain("跳过 2 条");
  });
});
