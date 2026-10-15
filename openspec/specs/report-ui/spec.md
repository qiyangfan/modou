# report-ui Specification

## Purpose
本地薄报告层：把 modou 产出的各类报告 JSON 经仅回环监听的只读网页渲染，
零外部请求、零存储；绑定只允许 IPv4 回环，报告内容（schema 元数据）不出本机。 add-report-ui. Update Purpose after archive.

## Requirements

### Requirement: 本地只读渲染

报告界面 SHALL 加载本地报告文件并渲染对应车道视图（验收 / 优化 / 审核 / 巡检），
数据 SHALL 全部来自所加载的报告文件，页面 SHALL NOT 发起任何外部网络请求，
SHALL NOT 提供编辑或执行操作。无法识别的报告类型或版本 SHALL 以输入错误失败
（退出码 2），错误消息 SHALL 列明支持的报告类型与版本。

#### Scenario: 渲染验收报告

- **GIVEN** 一份验收报告文件
- **WHEN** 用户启动报告界面
- **THEN** 按库分组展示三类结论条目与维度明细

#### Scenario: 未知报告版本

- **GIVEN** 报告文件的类型或版本标识不在支持清单
- **WHEN** 用户启动报告界面
- **THEN** 以退出码 2 失败，消息列明支持的报告类型与版本

#### Scenario: 页面零外部请求

- **GIVEN** 报告界面正在渲染任一视图
- **WHEN** 审查页面发起的网络请求
- **THEN** 除本机报告数据端点外无任何请求

### Requirement: 回环绑定

报告界面 SHALL 仅监听回环地址；请求绑定非回环地址 SHALL 被拒绝并以输入错误
退出（退出码 2）。SHALL NOT 提供登录、账号或远程访问能力。

#### Scenario: 默认绑定回环

- **GIVEN** 用户在本地启动报告界面且未指定绑定地址
- **WHEN** 服务开始监听
- **THEN** 仅回环地址上存在监听

#### Scenario: 外部绑定被拒

- **GIVEN** 用户传入非回环的绑定地址参数
- **WHEN** 启动命令
- **THEN** 以退出码 2 拒绝并说明仅支持本地访问

### Requirement: 零运行时外部依赖与干净生命周期

报告界面 SHALL 随工具安装即用：渲染所需资源 SHALL 随工具分发，运行期 SHALL NOT
要求前端构建工具链存在。用户终止时 SHALL 干净退出（退出码 0）且不残留监听；
输入报告不存在或不可读 SHALL 以退出码 2 失败。

#### Scenario: 无前端工具链环境可用

- **GIVEN** 未安装任何前端构建工具的机器
- **WHEN** 用户启动报告界面
- **THEN** 界面正常渲染

#### Scenario: 干净退出

- **GIVEN** 报告界面正在运行
- **WHEN** 用户发出终止信号
- **THEN** 进程以退出码 0 退出，不残留后台进程或监听

#### Scenario: 输入报告不可读

- **GIVEN** 传入的报告文件路径不存在
- **WHEN** 用户启动报告界面
- **THEN** 以退出码 2 失败并指明该路径
