// ── 巡检三类：漂移 / 索引 / 慢日志 ─────────────────────────────────────────
import type {
  PatrolDriftConclusion,
  PatrolSlowlogTop,
  PatrolUsage,
  ReportPayload,
} from "../types";
import {
  CASE_LABELS,
  CATEGORY_LABELS,
  STATUS_LABELS,
  card,
  detailCard,
  el,
} from "./shared";

interface RedundantRow {
  database: string;
  table: string;
  redundant_index: string;
  dominant_index: string;
  case: string;
  drop_statement: string;
  fk_protected: boolean;
}

export function renderPatrolDrift(
  root: HTMLElement,
  payload: ReportPayload,
): void {
  const data = payload.data as {
    summary?: { added: number; removed: number; changed: number };
    databases: Record<string, PatrolDriftConclusion[]>;
  };
  if (data.summary) {
    root.appendChild(
      card(
        el(
          "span",
          "summary-row",
          `新增 ${data.summary.added} · 缺失 ${data.summary.removed} · 定义变更 ${data.summary.changed}`,
        ),
      ),
    );
  }
  for (const [db, conclusions] of Object.entries(data.databases ?? {})) {
    root.appendChild(el("h2", undefined, `库 ${db}`));
    for (const conclusion of conclusions ?? []) {
      root.appendChild(driftCard(conclusion));
    }
  }
}

function driftCard(conclusion: PatrolDriftConclusion): HTMLElement {
  const badge = el(
    "span",
    `badge ${conclusion.category}`,
    CATEGORY_LABELS[conclusion.category] ?? conclusion.category,
  );
  return detailCard(badge, conclusion);
}

export function renderPatrolUnused(
  root: HTMLElement,
  payload: ReportPayload,
): void {
  const data = payload.data as {
    uptime_seconds: number | null;
    observe_days: number;
    usages: PatrolUsage[];
    redundancies: RedundantRow[];
  };
  renderUptimeNotice(root, data);
  for (const usage of data.usages ?? []) {
    root.appendChild(usageCard(usage));
  }
  for (const redundancy of data.redundancies ?? []) {
    root.appendChild(redundancyCard(redundancy));
  }
}

function renderUptimeNotice(
  root: HTMLElement,
  data: { uptime_seconds: number | null; observe_days: number },
): void {
  // 统计重置警示影响「确认未用」的可信度，必须在界面呈现
  if (data.uptime_seconds === undefined || data.uptime_seconds === null) return;
  const days = (data.uptime_seconds / 86400).toFixed(1);
  root.appendChild(
    card(
      el(
        "span",
        "summary-row",
        `服务器 uptime ${days} 天 · 观察窗 ${data.observe_days ?? "-"} 天`,
      ),
      el(
        "div",
        "muted",
        "I/O 统计会被重启/TRUNCATE/索引 DDL 重置：结论须交叉业务周期确认。",
      ),
    ),
  );
}

function usageCard(usage: PatrolUsage): HTMLElement {
  const line = card(
    el(
      "span",
      `badge ${usage.status === "confirmed_unused" ? "removed" : "info"}`,
      STATUS_LABELS[usage.status] ?? usage.status,
    ),
    el(
      "code",
      undefined,
      `${usage.database}.${usage.table}.${usage.index_name}`,
    ),
  );
  if (usage.drop_statement)
    line.appendChild(el("code", undefined, usage.drop_statement));
  const metrics: string[] = [];
  if (usage.daily_average !== null && usage.daily_average !== undefined) {
    metrics.push(`日均 ${usage.daily_average}`);
  }
  if (usage.table_share_pct !== null && usage.table_share_pct !== undefined) {
    metrics.push(`占同表 I/O ${usage.table_share_pct}%`);
  }
  if (metrics.length > 0)
    line.appendChild(el("div", "muted", metrics.join(" · ")));
  if (usage.note) line.appendChild(el("div", "muted", usage.note));
  return line;
}

function redundancyCard(redundancy: RedundantRow): HTMLElement {
  const fk = redundancy.fk_protected ? "· 外键依赖，先处理外键" : "";
  return card(
    el("span", "badge warning", "冗余"),
    el(
      "code",
      undefined,
      `${redundancy.database}.${redundancy.table}.${redundancy.redundant_index}`,
    ),
    el(
      "span",
      "muted",
      `被 ${redundancy.dominant_index} 覆盖（${CASE_LABELS[redundancy.case] ?? redundancy.case}）${fk}`,
    ),
    el("code", undefined, redundancy.drop_statement),
  );
}

export function renderPatrolSlowlog(
  root: HTMLElement,
  payload: ReportPayload,
): void {
  const data = payload.data as {
    entries_parsed: number;
    skipped_lines?: number;
    top: PatrolSlowlogTop[];
  };
  const skipped = data.skipped_lines ? ` · 跳过 ${data.skipped_lines} 条` : "";
  root.appendChild(
    card(
      el(
        "span",
        "summary-row",
        `解析条目 ${data.entries_parsed ?? "-"}${skipped} · 指纹榜 ${(data.top ?? []).length}`,
      ),
    ),
  );
  (data.top ?? []).forEach((top, index) => {
    root.appendChild(slowlogCard(top, index));
  });
}

function slowlogCard(top: PatrolSlowlogTop, index: number): HTMLElement {
  return card(
    el(
      "strong",
      undefined,
      `${index + 1}. 次数 ${top.count} · 累计 ${top.query_time_total.toFixed(3)}s · ` +
        `最大 ${top.query_time_max.toFixed(3)}s · 扫描 ${top.rows_examined_total} 行`,
    ),
    el("div", "muted", top.fingerprint),
    el("pre", undefined, top.sample),
  );
}
