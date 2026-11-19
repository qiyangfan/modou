// ── SQL 优化 ────────────────────────────────────────────────────────────────
import type {
  OptimizeStatement,
  OptimizeSuggestion,
  ReportPayload,
} from "../types";
import { card, el, rowsLine } from "./shared";

interface OptimizeData {
  exit_code: number;
  env_errors: string[];
  input_errors: string[];
  databases: Record<string, { statements: OptimizeStatement[] }>;
  evidence_env: {
    note: string;
    tables: {
      database: string;
      table: string;
      sampled_rows: number | null;
      estimated_rows: number | null;
    }[];
  };
  advisor: { configured: boolean };
}

export function renderOptimize(
  root: HTMLElement,
  payload: ReportPayload,
): void {
  const data = payload.data as unknown as OptimizeData;
  renderOptimizeErrors(root, data);
  renderEvidence(root, data.evidence_env);
  renderAdvisorNotice(root, data);
  renderStatements(root, data.databases);
}

function renderOptimizeErrors(root: HTMLElement, data: OptimizeData): void {
  // 失败报告（exit 2）的失败原因必须可见，不能只留「AI 未配置」误导
  for (const err of data.env_errors ?? []) {
    root.appendChild(
      card(el("span", "badge error", "环境错误"), el("span", undefined, err)),
    );
  }
  for (const err of data.input_errors ?? []) {
    root.appendChild(
      card(el("span", "badge error", "输入错误"), el("span", undefined, err)),
    );
  }
}

function renderEvidence(
  root: HTMLElement,
  evidence: OptimizeData["evidence_env"],
): void {
  if (!evidence?.note) return;
  const env = card(el("span", "muted", evidence.note));
  for (const t of evidence.tables ?? []) {
    const sampled =
      t.sampled_rows === null
        ? "未采样（无数据支撑代价对比）"
        : `采样 ${t.sampled_rows} 行`;
    env.appendChild(
      el(
        "div",
        "muted",
        `${t.database}.${t.table}：${sampled}（全表估计 ${t.estimated_rows ?? "未知"}）`,
      ),
    );
  }
  root.appendChild(env);
}

function renderAdvisorNotice(root: HTMLElement, data: OptimizeData): void {
  // 「AI 未配置」只在非失败报告上提示：失败报告的真因已在上方错误卡呈现
  if (
    data.advisor &&
    !data.advisor.configured &&
    !(data.env_errors ?? []).length &&
    !(data.input_errors ?? []).length
  ) {
    root.appendChild(
      card(
        el("span", "badge unverified", "AI 未配置"),
        el("span", "muted", "仅规则层产出候选"),
      ),
    );
  }
}

function renderStatements(
  root: HTMLElement,
  databases: OptimizeData["databases"],
): void {
  for (const [db, grouped] of Object.entries(databases ?? {})) {
    root.appendChild(el("h2", undefined, `库 ${db}`));
    for (const stmt of grouped.statements ?? []) {
      renderStatement(root, stmt);
    }
  }
}

function renderStatement(root: HTMLElement, stmt: OptimizeStatement): void {
  root.appendChild(
    card(
      el("span", "badge kind", `语句 #${stmt.index}`),
      el("pre", undefined, stmt.sql),
      el("div", "muted", `基线代价 ${stmt.baseline?.cost ?? "不可得"}`),
    ),
  );
  for (const finding of stmt.findings ?? []) {
    root.appendChild(
      card(
        el("span", "badge warning", "发现"),
        el("span", undefined, finding.message),
      ),
    );
  }
  for (const suggestion of stmt.suggestions ?? []) {
    root.appendChild(suggestionCard(suggestion));
  }
}

function suggestionCard(suggestion: OptimizeSuggestion): HTMLElement {
  const head =
    suggestion.status === "measured"
      ? el(
          "span",
          "badge measured",
          `实测提升 ${(suggestion.improvement_pct ?? 0).toFixed(1)}%`,
        )
      : el("span", "badge unverified", "未验证");
  const line = card(
    head,
    el(
      "span",
      "muted",
      `（${suggestion.source === "ai" ? "AI" : "规则"}·${suggestion.kind}）`,
    ),
    el("code", undefined, suggestion.content),
  );
  if (suggestion.status === "measured") {
    line.appendChild(
      el(
        "div",
        "muted",
        `代价 ${suggestion.cost_before} → ${suggestion.cost_after}`,
      ),
    );
    line.appendChild(
      el("div", "muted", rowsLine("扫描行数 前:", suggestion.rows_before)),
    );
    line.appendChild(
      el("div", "muted", rowsLine("扫描行数 后:", suggestion.rows_after)),
    );
  } else if (suggestion.reason) {
    line.appendChild(el("div", "muted", `原因：${suggestion.reason}`));
  }
  for (const note of suggestion.side_effects ?? []) {
    line.appendChild(el("div", "muted", `[附注·${note.kind}] ${note.message}`));
  }
  return line;
}
