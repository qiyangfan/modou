// 报告渲染入口：按报告类型分文件，保持对外 API 不变。
export { renderLint } from "./views/lint";
export { renderAiOpinions } from "./views/opinions";
export { renderOptimize } from "./views/optimize";
export {
  renderPatrolDrift,
  renderPatrolSlowlog,
  renderPatrolUnused,
} from "./views/patrol";
export { renderReport } from "./views/report";
export { el } from "./views/shared";
export { renderPatrolSummary } from "./views/summary";
export { renderVerify } from "./views/verify";
