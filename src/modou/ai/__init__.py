"""AI 分析师层（v0.5，ADR-0009）：确定性工程供证据、AI 做语义判断的内置通道。

模块构成：
- client：BYOK 客户端（stdlib HTTP、transport 注入可测、三元组缺一零网络），
  自 optimize/advisor.py 演进收拢于此（行为不变，现有测试守护）；
- slicer：schema 切片器——按语句触达裁剪元数据，token 预算上限可配置；
- bundler：变更分包器——按库/语句组分包，供调用方并发单轮后聚合；
- injector：规则注入器——lint 命中清单模板化注入（非自然语言转述）。

红线：本包只做上下文工程与受控调用；判定结论仍出自确定性代码与影子库，
AI 产物一律走 modou.report.opinions 的观点区契约（不碰退出码）。未配置
BYOK 三元组时，任何入口都不得发起网络请求。
"""
