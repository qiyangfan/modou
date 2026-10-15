# mcp-surface Specification

## ADDED Requirements

### Requirement: 工具与子命令一一对应

系统 SHALL 经 MCP 暴露与 CLI 分析类子命令一一对应的工具：每个工具的参数语义与
对应子命令一致，返回 SHALL 携带与该子命令机读出口同源的结构化报告及退出码语义
字段，工具描述 SHALL 与 CLI 帮助文案同义。交互式或长驻表面（报告界面、MCP 服务
自身）SHALL NOT 映射为工具。后续新增分析类子命令时工具清单 SHALL 同步扩展，
一致性 SHALL 由自动化校验守护（缺一或多一即校验失败）。

#### Scenario: 工具清单与子命令清单一致

- **GIVEN** CLI 已注册的分析类子命令集合与既定的非映射排除清单
- **WHEN** 自动化校验比对 MCP 工具名集合
- **THEN** 两集合一致，任何一侧多出或缺失即校验失败

#### Scenario: 工具返回与 CLI 同源

- **GIVEN** 同一变更集与快照输入
- **WHEN** 分别经 CLI 子命令与对应 MCP 工具执行
- **THEN** 两者的结构化报告内容一致，且工具返回含与 CLI 一致的退出码语义字段

### Requirement: 结构化返回与错误上报

每个工具 SHALL 返回机器可读的结构化结果。内核错误 SHALL 上报为携带英文消息的
工具错误，SHALL NOT 向客户端泄漏堆栈与内部路径。

#### Scenario: 输入错误上报

- **GIVEN** 工具收到不存在的路径参数
- **WHEN** 客户端调用该工具
- **THEN** 客户端收到指明参数问题的英文工具错误，无堆栈与内部路径泄漏

### Requirement: 本地 stdio 形态

MCP 表面 SHALL 仅以本地子进程与标准输入输出通道运行、由客户端按需拉起；
SHALL NOT 监听网络端口，SHALL NOT 常驻后台，SHALL NOT 提供远程访问与鉴权能力。
表面依赖未安装时 SHALL 以退出码 2 失败并给出依赖安装指引。

#### Scenario: 未安装可选依赖

- **GIVEN** 运行环境未安装 MCP 表面依赖
- **WHEN** 用户执行 MCP 启动命令
- **THEN** 命令以退出码 2 失败，错误消息含安装指引

#### Scenario: 无端口监听

- **GIVEN** MCP 表面正在运行
- **WHEN** 检查该进程的网络监听
- **THEN** 不存在任何监听套接字

### Requirement: 工具可组合完成端到端链路

分析类工具 SHALL 可在单一 MCP 会话内组合完成「打包校验变更集并优化其中慢 SQL」
的全链路；快照等输入以本地文件路径传递，SHALL NOT 要求用户在会话外手工中转
中间产物。

#### Scenario: agent 一句话链路

- **GIVEN** 样例变更集、执行前后快照与慢 SQL 文件已就位于本地
- **WHEN** agent 依一句话任务书在单一 MCP 会话内依次调用打包、验收、优化工具
- **THEN** 全链路完成，各环节报告可被 agent 读取并汇总作答

### Requirement: 托管 CI 集成示例仅限纯静态命令

系统 SHALL 提供托管 CI 的集成示例，示例中的命令 SHALL 仅限纯静态能力（零容器、
零数据库连接、零数据出本地）。示例 SHALL 以醒目方式声明：产物含生产 schema 的
命令（如执行后验收）禁止进入托管 CI 环境。

#### Scenario: 示例仅含纯静态步骤

- **GIVEN** 发布的 CI 集成示例
- **WHEN** 审查其执行步骤
- **THEN** 仅含打包预警类命令，无容器编排与数据库连接步骤

#### Scenario: 红线声明在场

- **GIVEN** 用户阅读 CI 集成示例文档
- **WHEN** 查找关于验收类命令能否进 CI 的说明
- **THEN** 文档明确声明其产物含生产 schema、禁止进入托管 CI
