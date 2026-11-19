// ── 变更验收 ────────────────────────────────────────────────────────────────
import type { ReportPayload, VerifyConclusion } from "../types";
import { card, detailTable, el } from "./shared";

interface VerifyData {
  exit_code: number;
  summary: Record<string, number>;
  env_errors: string[];
  input_errors?: string[];
  replay_error: {
    statement_index: number;
    error_code: number;
    error_message: string;
    sql: string;
  } | null;
  pack_warnings: {
    source_file: string;
    statement_index: number;
    kind: string;
    level: string;
    message: string;
  }[];
  databases: Record<string, VerifyConclusion[]>;
}

const CONCLUSION_LABELS: Record<string, string> = {
  missing_execution: "漏执行",
  wrong_execution: "错执行",
  historical_drift: "历史漂移",
};

export function renderVerify(root: HTMLElement, payload: ReportPayload): void {
  const data = payload.data as unknown as VerifyData;
  const envErrors = data.env_errors ?? [];
  renderVerifyHeader(root, data);
  renderVerifyErrors(root, data, envErrors);
  const databases = data.databases ?? {};
  const names = Object.keys(databases);
  if (names.length === 0) {
    renderAllConsistent(root, data, envErrors);
    return;
  }
  renderVerifyDatabases(root, names, databases);
}

function renderVerifyHeader(root: HTMLElement, data: VerifyData): void {
  root.appendChild(
    card(
      el("span", "badge kind", `退出码 ${data.exit_code ?? "-"}`),
      el(
        "span",
        "summary-row",
        `漏执行 ${data.summary?.missing_execution ?? 0} · 错执行 ${
          data.summary?.wrong_execution ?? 0
        } · 历史漂移 ${data.summary?.historical_drift ?? 0}`,
      ),
    ),
  );
}

function renderVerifyErrors(
  root: HTMLElement,
  data: VerifyData,
  envErrors: string[],
): void {
  for (const err of envErrors) {
    root.appendChild(
      card(
        el("span", "badge error", "环境/输入错误"),
        el("span", undefined, err),
      ),
    );
  }
  for (const err of data.input_errors ?? []) {
    root.appendChild(
      card(el("span", "badge error", "输入错误"), el("span", undefined, err)),
    );
  }
  if (data.replay_error) {
    const err = data.replay_error;
    root.appendChild(
      card(
        el("span", "badge error", "回放失败"),
        el(
          "span",
          undefined,
          `语句 #${err.statement_index}（error ${err.error_code}）：${err.error_message}`,
        ),
        el("pre", undefined, err.sql),
      ),
    );
  }
  for (const warning of data.pack_warnings ?? []) {
    root.appendChild(
      card(
        el("span", "badge warning", "打包预警"),
        el(
          "span",
          undefined,
          `${warning.source_file} #${warning.statement_index}：${warning.message}`,
        ),
      ),
    );
  }
}

function renderAllConsistent(
  root: HTMLElement,
  data: VerifyData,
  envErrors: string[],
): void {
  // 「全部一致」只在验收真正成立时出现：有环境错误/回放失败的空 databases 不是一致
  if (data.exit_code === 0 && envErrors.length === 0 && !data.replay_error) {
    root.appendChild(
      card(el("span", undefined, "全部一致：期望态与实际态逐对象逐维度相等。")),
    );
  }
}

function renderVerifyDatabases(
  root: HTMLElement,
  names: string[],
  databases: Record<string, VerifyConclusion[]>,
): void {
  for (const db of names) {
    root.appendChild(el("h2", undefined, `库 ${db}`));
    for (const conclusion of databases[db] ?? []) {
      root.appendChild(conclusionCard(conclusion));
    }
  }
}

function conclusionCard(conclusion: VerifyConclusion): HTMLElement {
  const badgeClass =
    conclusion.kind === "missing_execution"
      ? "removed"
      : conclusion.kind === "wrong_execution"
        ? "error"
        : "changed";
  return card(
    el(
      "span",
      `badge ${badgeClass}`,
      CONCLUSION_LABELS[conclusion.kind] ?? conclusion.kind,
    ),
    el(
      "strong",
      undefined,
      `${conclusion.object_type} ${conclusion.object_name}`,
    ),
    el("div", "muted", `维度：${(conclusion.dimensions ?? []).join("、")}`),
    detailTable(conclusion.details ?? []),
  );
}
