// ── AI 观点区（两级标注的呈现面：无观点恒等，不做二次计算）──────────────────
import type { AiOpinion } from "../types";
import { card, el } from "./shared";

export function renderAiOpinions(
  root: HTMLElement,
  data: Record<string, unknown>,
): void {
  const opinions = data.ai_opinions;
  if (!Array.isArray(opinions) || opinions.length === 0) return;
  root.appendChild(
    el("h2", undefined, "AI 观点（模型输出·未经实证·不影响退出码）"),
  );
  for (const raw of opinions as AiOpinion[]) {
    root.appendChild(opinionCard(raw));
  }
}

function opinionCard(opinion: AiOpinion): HTMLElement {
  const head =
    opinion.status === "degraded"
      ? el(
          "span",
          "badge warning",
          `降级（${opinion.degraded_reason ?? "未知原因"}）`,
        )
      : el("span", "badge unverified", "AI 观点");
  return card(
    head,
    el("span", "muted", `${opinion.lane} · ${opinion.subject}`),
    el("div", undefined, opinion.opinion),
    el("span", "muted", `来源 ${opinion.source}:${opinion.model}`),
  );
}
