# ai-analyst Specification

## ADDED Requirements

### Requirement: 结论两级分级

AI 产物 SHALL 与确定性结论分级标注：**实证已验证**（判定出自确定性代码与影子库
实测）与 **AI 观点**（附来源与未实证标注）。AI 观点 SHALL 在报告中单列展示，
SHALL NOT 影响任何命令的退出码；退出码 SHALL 仅由确定性结论决定。

#### Scenario: AI 观点不碰退出码

- **GIVEN** 已配置 AI 端点且模型返回了观点
- **WHEN** 产出报告
- **THEN** AI 观点在报告单列区展示并附来源标注，退出码仅由确定性结论决定

#### Scenario: 未配置时零差异

- **GIVEN** 未配置任何 AI 端点
- **WHEN** 执行任意车道命令
- **THEN** 不发起任何网络请求，报告不含 AI 观点区，行为与无 AI 能力的版本一致

#### Scenario: 调用失败降级

- **GIVEN** 已配置 AI 端点但调用超时或返回不可解析
- **WHEN** 产出报告
- **THEN** AI 观点区标注降级原因，报告照常产出，退出码不变

### Requirement: 证据预取的受控调用

内置 AI 分析 SHALL 由确定性流水线预取证据并构造请求上下文（按语句触达裁剪
schema、变更分组、已命中规则注入），SHALL NOT 依赖模型在会话中自主获取数据；
模型输出 SHALL 为结构化格式并逐条校验，不可解析条目 SHALL 丢弃且不导致整体失败。
请求上下文 SHALL 仅含 schema 元数据与 SQL 文本，SHALL NOT 含采样数据行。

#### Scenario: 上下文按触达裁剪

- **GIVEN** 一条仅触达单个表的语句
- **WHEN** 构造 AI 请求上下文
- **THEN** schema 元数据仅含该表所属库的相关子集，不含无关库表

#### Scenario: 不可解析条目逐条丢弃

- **GIVEN** 模型返回中部分条目不符合约定结构
- **WHEN** 解析模型输出
- **THEN** 非法条目被丢弃，合法条目保留，整体调用不视为失败

#### Scenario: 数据不出本地

- **GIVEN** 任意内置 AI 分析请求
- **WHEN** 检查请求载荷
- **THEN** 载荷仅含 SQL 文本与 schema 元数据，不含任何数据行

### Requirement: 宿主委托面

系统 SHALL 提供供宿主 Agent 调用的证据原语（快照摘要、回放验收、三方 diff、
执行计划、规则命中），每个证据原语 SHALL 与对应命令的机读出口对齐并受一致性
校验守护；证据原语 SHALL 在未配置 AI 端点时完整可用。

#### Scenario: 零密钥委托链路

- **GIVEN** 未配置任何 AI 端点的宿主 Agent
- **WHEN** 仅通过证据原语操作
- **THEN** 打包、影子库验收与报告解读链路完整可用

#### Scenario: 证据原语与命令出口一致

- **GIVEN** 任一证据原语
- **WHEN** 与其对应命令的机读出口对比
- **THEN** 二者结构一致，一致性校验守护通过
