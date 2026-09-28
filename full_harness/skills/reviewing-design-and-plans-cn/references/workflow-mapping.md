# 工作流与产物映射

## 目录

1. 公共事实源
2. Trellis
3. OpenSpec
4. Superpowers 与普通 Markdown
5. 原型和实现验证

## 公共事实源

优先遵守项目自己的路径。没有项目约定时使用以下语义，不强制目录名：

| 语义 | 常见公共位置 |
|---|---|
| 产品基线 | `docs/00-global/`、`docs/product/` |
| 架构基线 | `docs/01-architecture/`、`docs/architecture/` |
| 交付计划 | `docs/delivery/`、`docs/04-implementation/` |
| 验收证据 | `docs/05-validation/`、`docs/validation/` |

公共事实源需要进入团队仓库、可追溯并可由不同 Agent 读取。个人工具的运行日志、缓存、检查点和对话记录不能代替它。

## Trellis

| Trellis 产物 | 评审角色 |
|---|---|
| `.trellis/tasks/<task>/prd.md` | 当前任务范围、要求和 AC；必须追溯公共 PRD |
| `design.md` | 当前任务技术设计；执行 `G2 LLD READY` 或任务级 `DESIGN READY` |
| `implement.md` | 实施顺序与验证计划；执行 `G3 PLAN READY` |
| `implement.jsonl` | 可分发实施项；作为计划覆盖和粒度证据 |
| `check.jsonl` | 验证责任；作为计划验收覆盖证据 |
| `.trellis/spec/` | 项目编码和实现约束；是评审规则，不是产品需求来源 |

Trellis 的任务 PRD 细化公共需求，不重写公共产品决定。任务设计发现上游冲突时返回 `UPSTREAM REOPEN` 或 `DECISION REQUIRED`。

## OpenSpec

把 proposal、spec、design、tasks 分别映射为范围、行为契约、技术决策和实施责任。运行项目规定的只读校验器；校验器不可用时标记未验证，不自动安装或改环境。

OpenSpec delta 不得静默改变主 Spec。涉及 `MODIFIED` 或 `REMOVED` 时核对主 Spec 的对应 Requirement；纯新增能力仍要检查是否属于已批准范围。

## Superpowers 与普通 Markdown

Superpowers 的 design spec 作为技术设计，implementation plan 作为实施计划。普通 Markdown 按内容责任映射，不要求改造成特定格式。

计划至少需要：行为目标、稳定位置或模块、依赖、约束、最小验证和通过标准。不要强制每项任务附大段代码、逐文件任务或机械提交次数。

## 原型和实现验证

当 PRD 把用户可见行为纳入范围时，原型和交互规范是设计证据：检查页面、角色、动作、状态和失败反馈是否承接 AC。

视觉还原、浏览器旅程、实现代码和目标环境运行结果属于后续验证：

- 原型视觉和交互：浏览器验收；
- 代码正确性：Review、Trellis Check、自动化测试；
- 组件能力和集群行为：目标环境技术验证；
- 发布判断：Release/Validation Gate。

设计评审只确认这些验证有明确责任、环境和通过标准，不假装已经执行。
