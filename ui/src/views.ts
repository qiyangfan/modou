// 四类车道视图：只读渲染，全部数据来自所加载的报告（零外部请求）
// 渲染入口（renderReport）对畸形报告兜底为错误卡，各 renderer 内部字段访问带缺省
import type {
  AiOpinion,
  LintHit,
  OptimizeStatement,
  PatrolDriftConclusion,
  PatrolSlowlogTop,
  PatrolSummarySignals,
  PatrolUsage,
  ReportPayload,
  VerifyConclusion,
} from "./types";
import { KIND_LABELS } from "./types";

export function el(tag: string, className?: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function card(...children: HTMLElement[]): HTMLElement {
  const box = el("div", "card");
  children.forEach((c) => box.appendChild(c));
  return box;
}

function detailTable(details: { path: string; expected: string; actual: string }[]): HTMLElement {
  const table = el("table");
  const head = el("tr");
  ["对象/路径", "期望", "实际"].forEach((t) => head.appendChild(el("th", undefined, t)));
  table.appendChild(head);
  for (const d of details) {
    const row = el("tr");
    row.appendChild(el("td", undefined, d.path));
    row.appendChild(el("td", undefined, d.expected));
    row.appendChild(el("td", undefined, d.actual));
    table.appendChild(row);
  }
  return table;
}

function rowsLine(label: string, accesses: { table: string; rows: number }[] | undefined): string {
  const items = (accesses ?? []).map((a) => `${a.table}=${a.rows}`);
  return items.length > 0 ? `${label} ${items.join(" · ")}` : `${label} —`;
}

// ── 变更验收 ────────────────────────────────────────────────────────────────
export function renderVerify(root: HTMLElement, payload: ReportPayload): void {
  const data = payload.data as {
    exit_code: number;
    summary: Record<string, number>;
    env_errors: string[];
    input_errors?: string[];
    replay_error: { statement_index: number; error_code: number; error_message: string; sql: string } | null;
    pack_warnings: { source_file: string; statement_index: number; kind: string; level: string; message: string }[];
    databases: Record<string, VerifyConclusion[]>;
  };
  const envErrors = data.env_errors ?? [];
  root.appendChild(
    card(
      el("span", "badge kind", `退出码 ${data.exit_code ?? "-"}`),
      el(
        "span",
        "summary-row",
        `漏执行 ${data.summary?.missing_execution ?? 0} · 错执行 ${data.summary?.wrong_execution ?? 0} · 历史漂移 ${
          data.summary?.historical_drift ?? 0
        }`,
      ),
    ),
  );
  for (const err of envErrors) {
    root.appendChild(card(el("span", "badge error", "环境/输入错误"), el("span", undefined, err)));
  }
  for (const err of data.input_errors ?? []) {
    root.appendChild(card(el("span", "badge error", "输入错误"), el("span", undefined, err)));
  }
  if (data.replay_error) {
    const err = data.replay_error;
    root.appendChild(
      card(
        el("span", "badge error", "回放失败"),
        el("span", undefined, `语句 #${err.statement_index}（error ${err.error_code}）：${err.error_message}`),
        el("pre", undefined, err.sql),
      ),
    );
  }
  for (const w of data.pack_warnings ?? []) {
    root.appendChild(
      card(el("span", "badge warning", "打包预警"), el("span", undefined, `${w.source_file} #${w.statement_index}：${w.message}`)),
    );
  }
  const databases = data.databases ?? {};
  const names = Object.keys(databases);
  if (names.length === 0) {
    // 「全部一致」只在验收真正成立时出现：有环境错误/回放失败的空 databases 不是一致
    if (data.exit_code === 0 && envErrors.length === 0 && !data.replay_error) {
      root.appendChild(card(el("span", undefined, "全部一致：期望态与实际态逐对象逐维度相等。")));
    }
    return;
  }
  const kindLabel: Record<string, string> = {
    missing_execution: "漏执行",
    wrong_execution: "错执行",
    historical_drift: "历史漂移",
  };
  for (const db of names) {
    root.appendChild(el("h2", undefined, `库 ${db}`));
    for (const c of databases[db] ?? []) {
      root.appendChild(
        card(
          el(
            "span",
            `badge ${c.kind === "missing_execution" ? "removed" : c.kind === "wrong_execution" ? "error" : "changed"}`,
            kindLabel[c.kind] ?? c.kind,
          ),
          el("strong", undefined, `${c.object_type} ${c.object_name}`),
          el("div", "muted", `维度：${(c.dimensions ?? []).join("、")}`),
          detailTable(c.details ?? []),
        ),
      );
    }
  }
}

// ── SQL 优化 ────────────────────────────────────────────────────────────────
export function renderOptimize(root: HTMLElement, payload: ReportPayload): void {
  const data = payload.data as {
    exit_code: number;
    env_errors: string[];
    input_errors: string[];
    databases: Record<string, { statements: OptimizeStatement[] }>;
    evidence_env: {
      note: string;
      tables: { database: string; table: string; sampled_rows: number | null; estimated_rows: number | null }[];
    };
    advisor: { configured: boolean };
  };
  // 失败报告（exit 2）的失败原因必须可见，不能只留「AI 未配置」误导
  for (const err of data.env_errors ?? []) {
    root.appendChild(card(el("span", "badge error", "环境错误"), el("span", undefined, err)));
  }
  for (const err of data.input_errors ?? []) {
    root.appendChild(card(el("span", "badge error", "输入错误"), el("span", undefined, err)));
  }
  const evidence = data.evidence_env;
  if (evidence?.note) {
    const env = card(el("span", "muted", evidence.note));
    for (const t of evidence.tables ?? []) {
      const sampled = t.sampled_rows === null ? "未采样（无数据支撑代价对比）" : `采样 ${t.sampled_rows} 行`;
      env.appendChild(
        el("div", "muted", `${t.database}.${t.table}：${sampled}（全表估计 ${t.estimated_rows ?? "未知"}）`),
      );
    }
    root.appendChild(env);
  }
  // 「AI 未配置」只在非失败报告上提示：失败报告的真因已在上方错误卡呈现
  if (
    data.advisor &&
    !data.advisor.configured &&
    !(data.env_errors ?? []).length &&
    !(data.input_errors ?? []).length
  ) {
    root.appendChild(card(el("span", "badge unverified", "AI 未配置"), el("span", "muted", "仅规则层产出候选")));
  }
  for (const [db, grouped] of Object.entries(data.databases ?? {})) {
    root.appendChild(el("h2", undefined, `库 ${db}`));
    for (const stmt of grouped.statements ?? []) {
      const box = card(
        el("span", "badge kind", `语句 #${stmt.index}`),
        el("pre", undefined, stmt.sql),
        el("div", "muted", `基线代价 ${stmt.baseline?.cost ?? "不可得"}`),
      );
      root.appendChild(box);
      for (const f of stmt.findings ?? []) {
        root.appendChild(card(el("span", "badge warning", "发现"), el("span", undefined, f.message)));
      }
      for (const s of stmt.suggestions ?? []) {
        const head =
          s.status === "measured"
            ? el("span", "badge measured", `实测提升 ${(s.improvement_pct ?? 0).toFixed(1)}%`)
            : el("span", "badge unverified", "未验证");
        const line = card(head, el("span", "muted", `（${s.source === "ai" ? "AI" : "规则"}·${s.kind}）`), el("code", undefined, s.content));
        if (s.status === "measured") {
          line.appendChild(el("div", "muted", `代价 ${s.cost_before} → ${s.cost_after}`));
          line.appendChild(el("div", "muted", rowsLine("扫描行数 前:", s.rows_before)));
          line.appendChild(el("div", "muted", rowsLine("扫描行数 后:", s.rows_after)));
        } else if (s.reason) {
          line.appendChild(el("div", "muted", `原因：${s.reason}`));
        }
        for (const note of s.side_effects ?? []) {
          line.appendChild(el("div", "muted", `[附注·${note.kind}] ${note.message}`));
        }
        root.appendChild(line);
      }
    }
  }
}

// ── 规则审核 ────────────────────────────────────────────────────────────────
export function renderLint(root: HTMLElement, payload: ReportPayload): void {
  const data = payload.data as { summary: { hits: number }; hits: LintHit[] };
  root.appendChild(card(el("span", "summary-row", `命中 ${data.summary?.hits ?? 0} 条`)));
  const table = el("table");
  const head = el("tr");
  ["级别", "规则", "位置", "消息", "建议"].forEach((t) => head.appendChild(el("th", undefined, t)));
  table.appendChild(head);
  for (const hit of data.hits ?? []) {
    const row = el("tr");
    const level = el("td");
    level.appendChild(el("span", `badge ${hit.level}`, hit.level));
    row.appendChild(level);
    row.appendChild(el("td", undefined, hit.rule_id));
    row.appendChild(el("td", undefined, `${hit.file}:${hit.line}`));
    row.appendChild(el("td", undefined, hit.message));
    row.appendChild(el("td", undefined, hit.suggestion));
    table.appendChild(row);
  }
  root.appendChild(card(table));
}

// ── 巡检三类 ────────────────────────────────────────────────────────────────
export function renderPatrolDrift(root: HTMLElement, payload: ReportPayload): void {
  const data = payload.data as {
    summary?: { added: number; removed: number; changed: number };
    databases: Record<string, PatrolDriftConclusion[]>;
  };
  const summary = data.summary;
  if (summary) {
    root.appendChild(
      card(el("span", "summary-row", `新增 ${summary.added} · 缺失 ${summary.removed} · 定义变更 ${summary.changed}`)),
    );
  }
  const categoryLabel: Record<string, string> = { added: "新增", removed: "缺失", changed: "定义变更" };
  for (const [db, conclusions] of Object.entries(data.databases ?? {})) {
    root.appendChild(el("h2", undefined, `库 ${db}`));
    for (const c of conclusions ?? []) {
      root.appendChild(
        card(
          el("span", `badge ${c.category}`, categoryLabel[c.category] ?? c.category),
          el("strong", undefined, `${c.object_type} ${c.object_name}`),
          el("div", "muted", `维度：${(c.dimensions ?? []).join("、")}`),
          detailTable(c.details ?? []),
        ),
      );
    }
  }
}

export function renderPatrolUnused(root: HTMLElement, payload: ReportPayload): void {
  const data = payload.data as {
    uptime_seconds: number | null;
    observe_days: number;
    usages: PatrolUsage[];
    redundancies: { database: string; table: string; redundant_index: string; dominant_index: string; case: string; drop_statement: string; fk_protected: boolean }[];
  };
  // 统计重置警示影响「确认未用」的可信度，必须在界面呈现
  if (data.uptime_seconds !== undefined && data.uptime_seconds !== null) {
    const days = (data.uptime_seconds / 86400).toFixed(1);
    root.appendChild(
      card(
        el("span", "summary-row", `服务器 uptime ${days} 天 · 观察窗 ${data.observe_days ?? "-"} 天`),
        el("div", "muted", "I/O 统计会被重启/TRUNCATE/索引 DDL 重置：结论须交叉业务周期确认。"),
      ),
    );
  }
  const statusLabel: Record<string, string> = {
    confirmed_unused: "确认未用",
    low_use: "疑似低用",
    insufficient_data: "数据不足",
    excluded_unique: "排除（唯一性）",
    excluded_fk: "排除（外键）",
  };
  for (const u of data.usages ?? []) {
    const line = card(el("span", `badge ${u.status === "confirmed_unused" ? "removed" : "info"}`, statusLabel[u.status] ?? u.status), el("code", undefined, `${u.database}.${u.table}.${u.index_name}`));
    if (u.drop_statement) line.appendChild(el("code", undefined, u.drop_statement));
    const metrics: string[] = [];
    if (u.daily_average !== null && u.daily_average !== undefined) metrics.push(`日均 ${u.daily_average}`);
    if (u.table_share_pct !== null && u.table_share_pct !== undefined) metrics.push(`占同表 I/O ${u.table_share_pct}%`);
    if (metrics.length > 0) line.appendChild(el("div", "muted", metrics.join(" · ")));
    if (u.note) line.appendChild(el("div", "muted", u.note));
    root.appendChild(line);
  }
  const caseLabel: Record<string, string> = {
    duplicate: "列集合完全相同",
    prefix_non_unique: "非唯一前缀覆盖",
    unique_prefix: "唯一前缀使更长索引冗余",
  };
  for (const r of data.redundancies ?? []) {
    root.appendChild(
      card(
        el("span", "badge warning", "冗余"),
        el("code", undefined, `${r.database}.${r.table}.${r.redundant_index}`),
        el("span", "muted", `被 ${r.dominant_index} 覆盖（${caseLabel[r.case] ?? r.case}）${r.fk_protected ? "· 外键依赖，先处理外键" : ""}`),
        el("code", undefined, r.drop_statement),
      ),
    );
  }
}

export function renderPatrolSlowlog(root: HTMLElement, payload: ReportPayload): void {
  const data = payload.data as { entries_parsed: number; skipped_lines?: number; top: PatrolSlowlogTop[] };
  const skipped = data.skipped_lines ? ` · 跳过 ${data.skipped_lines} 条` : "";
  root.appendChild(
    card(el("span", "summary-row", `解析条目 ${data.entries_parsed ?? "-"}${skipped} · 指纹榜 ${(data.top ?? []).length}`)),
  );
  (data.top ?? []).forEach((t, index) => {
    root.appendChild(
      card(
        el("strong", undefined, `${index + 1}. 次数 ${t.count} · 累计 ${t.query_time_total.toFixed(3)}s · 最大 ${t.query_time_max.toFixed(3)}s · 扫描 ${t.rows_examined_total} 行`),
        el("div", "muted", t.fingerprint),
        el("pre", undefined, t.sample),
      ),
    );
  });
}

// ── 综合巡检 ────────────────────────────────────────────────────────────────
export function renderPatrolSummary(root: HTMLElement, payload: ReportPayload): void {
  const data = payload.data as {
    exit_code: number;
    generated_at?: string;
    inputs?: Record<string, string | null>;
    signals: PatrolSummarySignals;
  };
  root.appendChild(card(el("span", "badge kind", `退出码 ${data.exit_code ?? "-"}`)));
  const sources = Object.entries(data.inputs ?? {})
    .map(([signal, source]) => `${signal}=${source ?? "—"}`)
    .join(" · ");
  if (sources) {
    root.appendChild(card(el("span", "muted", `输入来源 ${sources}`)));
  }
  const signals = data.signals ?? {};
  const categoryLabel: Record<string, string> = { added: "新增", removed: "缺失", changed: "定义变更" };
  const statusLabel: Record<string, string> = {
    confirmed_unused: "确认未用",
    low_use: "疑似低用",
    insufficient_data: "数据不足",
    excluded_unique: "排除（唯一性）",
    excluded_fk: "排除（外键）",
  };
  if (signals.drift) {
    const s = signals.drift;
    root.appendChild(card(el("span", "summary-row", `漂移：新增 ${s.added} · 缺失 ${s.removed} · 定义变更 ${s.changed}`)));
    for (const o of s.objects ?? []) {
      root.appendChild(
        card(
          el("span", `badge ${o.category}`, categoryLabel[o.category] ?? o.category),
          el("code", undefined, `${o.database}.${o.object_type}:${o.object_name}`),
        ),
      );
    }
  }
  if (signals.unused) {
    const s = signals.unused;
    root.appendChild(
      card(
        el(
          "span",
          "summary-row",
          `未用索引：确认未用 ${s.confirmed_unused} · 疑似低用 ${s.low_use} · 数据不足 ${s.insufficient_data} · 冗余 ${s.redundant}`,
        ),
      ),
    );
    for (const item of s.items ?? []) {
      root.appendChild(
        card(el("code", undefined, `${item.database}.${item.table}.${item.index}`), el("span", "muted", statusLabel[item.status] ?? item.status)),
      );
    }
  }
  if (signals.slowlog) {
    const s = signals.slowlog;
    root.appendChild(card(el("span", "summary-row", `慢日志：解析条目 ${s.entries_parsed} · 指纹榜 ${s.fingerprints}`)));
    for (const t of s.top ?? []) {
      root.appendChild(
        card(
          el("strong", undefined, `次数 ${t.count} · 累计 ${t.query_time_total.toFixed(3)}s · 扫描 ${t.rows_examined_total} 行`),
          el("div", "muted", t.fingerprint),
        ),
      );
    }
  }
  root.appendChild(card(el("div", "muted", "明细为摘要截断（对象 ≤20 · 指纹前 3），完整结论见各信号报告。")));
}

// ── AI 观点区（两级标注的呈现面：无观点恒等，不做二次计算）──────────────────
export function renderAiOpinions(root: HTMLElement, data: Record<string, unknown>): void {
  const opinions = data.ai_opinions;
  if (!Array.isArray(opinions) || opinions.length === 0) return;
  root.appendChild(el("h2", undefined, "AI 观点（模型输出·未经实证·不影响退出码）"));
  for (const raw of opinions as AiOpinion[]) {
    const head =
      raw.status === "degraded"
        ? el("span", "badge warning", `降级（${raw.degraded_reason ?? "未知原因"}）`)
        : el("span", "badge unverified", "AI 观点");
    root.appendChild(
      card(head, el("span", "muted", `${raw.lane} · ${raw.subject}`), el("div", undefined, raw.opinion), el("span", "muted", `来源 ${raw.source}:${raw.model}`)),
    );
  }
}

export function renderReport(root: HTMLElement, payload: ReportPayload): void {
  root.replaceChildren();
  root.appendChild(el("h2", undefined, `${KIND_LABELS[payload.kind] ?? payload.kind}（${payload.source}）`));
  try {
    switch (payload.kind) {
      case "verify":
        renderVerify(root, payload);
        break;
      case "optimize":
        renderOptimize(root, payload);
        break;
      case "lint":
        renderLint(root, payload);
        break;
      case "patrol_drift":
        renderPatrolDrift(root, payload);
        break;
      case "patrol_unused_indexes":
        renderPatrolUnused(root, payload);
        break;
      case "patrol_slowlog":
        renderPatrolSlowlog(root, payload);
        break;
      case "patrol_summary":
        renderPatrolSummary(root, payload);
        break;
      default: {
        const unknown: never = payload.kind;
        root.appendChild(card(el("span", "badge error", `未知报告类型：${String(unknown)}`)));
      }
    }
    renderAiOpinions(root, payload.data);
  } catch {
    // kind/version 门禁放行但缺契约字段的报告（手写/截断/旧版）：错误卡而非白屏
    root.appendChild(
      card(el("span", "badge error", "报告解析失败"), el("span", "muted", "报告结构不完整或与契约不符，无法渲染。")),
    );
  }
}
