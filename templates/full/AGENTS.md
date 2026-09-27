# Project working agreement

Read `docs/README.md` before starting a task. Follow its links to project purpose, current behavior, accepted decisions and applicable task documents. Check the actual code when documents disagree; report the conflict rather than silently choosing a new direction.

- Reuse accepted documents, interfaces and project conventions. Keep this file independent of release numbers.
- Deliver complete basic user journeys, including creation of required objects and failure paths. Direct database edits or fabricated data do not prove a user journey works.
- Persist decisions and material implementation changes in shared documents. Private agent conversations are not the project knowledge base.
- Ask for clarification only when a product decision, material ambiguity or unavailable prerequisite prevents progress. Investigate facts yourself.
- Use `.harness/full.json` for stage handoff paths and verification commands. Its checks and workflow controls are Owner-managed.
- See `docs/harness-full.md` for the independent full workflow, stage outputs and resumption contract.


## Python quality

Use Ruff with 4-space indentation, double quotes, 88-character target line width, and the shared `full_harness/ruff.toml` rules. After editing product Python code, run `python3 full_harness/quality.py fix`, repair remaining errors, then run `python3 full_harness/quality.py check`. The Stop Hook and verification stage run read-only checks independently. Formatting and lint never replace functional tests. Do not weaken quality rules to pass a task. Install the pinned tool using `python3 -m pip install -r full_harness/requirements.txt` in the Runner environment.

<!-- harness-stage-deliverables -->
## 阶段产物与 Skill 入口

开始或恢复每一轮时，重新读取本文件和 `docs/README.md`，再读取当前任务的已确认基线。阶段只划分工作责任，不缩减 Skill 的执行步骤、必读参考和交付要求；遵循当前阶段 Skill 及其引用的输出契约，不只读取目录就声明完成。执行协议负责 Session、消息和阶段接续，不重新定义设计方法。

| 阶段 | 交付物与默认位置 | 方法入口（按需渐进读取） |
|---|---|---|
| requirements | `docs/04-implementation/tasks/<issue>/prd.md`：PRD、User Story、AC；产品决策及澄清记录按 Skill 落盘。引用已有原型和基线，给出设计阶段输入。 | `full_harness/skills/resumable-batch-grilling/SKILL.md`、`full_harness/skills/defining-platform-products-cn/SKILL.md` |
| design：交互与原型 | `docs/04-implementation/tasks/<issue>/prototype/`：涉及用户界面的变更交付可运行、可预览的交互原型，运行说明、关键状态与截图证据。文字线框和已有产品截图不能代替本次变更的原型。非界面产品说明对应交互方式与适用性。 | 承接 PRD、AC 与项目既有 UI／原型规范；遵循 Owner 配置的原型 Skill（如有） |
| design：架构与契约 | `docs/01-architecture/tasks/<issue>/hld.md`、`contracts.md`：HLD、数据／API 契约；架构决策记录、台账和必要技术验证依架构 Skill 产出。以 `docs/04-implementation/tasks/<issue>/design/README.md` 索引完整文件集合。 | `full_harness/skills/platform-architecture-v2-cn/SKILL.md` 及其输出、HLD、追溯参考；`full_harness/skills/reviewing-design-and-plans-cn/SKILL.md` 核对本阶段产物 |
| development | `docs/04-implementation/tasks/<issue>/`：实施计划、任务拆解；`docs/01-architecture/tasks/<issue>/`：LLD 与契约细化；业务代码、测试及 `docs/05-validation/tasks/<issue>/validation.md` 验证证据，维护公共进度与规范。 | `full_harness/skills/managing-engineering-delivery-cn/SKILL.md`、`full_harness/skills/trellis-before-dev/SKILL.md`、`full_harness/skills/trellis-check/SKILL.md`、`full_harness/skills/trellis-update-spec/SKILL.md` |

- 已有项目沿用其权威路径，在 `docs/README.md` 和任务索引中说明对应关系；引用已有产物，不建立两套事实源。默认路径不是对 Skill 产物数量或种类的限制。
- 交互原型与架构设计属于同一个 design 阶段，分别提供可审查的产物。`design/README.md` 只做索引，不能用一个 `design.md` 或摘要代替原型、HLD、契约和 Skill 要求的记录。
- 明确列出本轮新建、更新、复用的文件及验证证据；需要裁剪约定产物时，说明理由和影响，请用户确认后再裁剪，不能因为任务小、已有页面或“轻量流程”而自行省略。发现 Skill 缺失或约定冲突时指出具体缺口，不自创替代流程。
- 提交需求或设计确认前，按对应 Skill 自查完整性、需求追溯与跨文档一致性；没有执行评审就不声称“评审通过”。轻量流程由本阶段 Agent 完成自查，不额外启动评审模型。
- 在 `artifacts` 列出供本次审查的真实文件集合（包括原型运行依赖及证据），回复中说明已完成什么、还缺什么、需要用户确认什么。确认范围绑定完整交付集合，不能只确认索引而遗漏其引用文件。普通问答无需重复提交整包。
- 中途接入时先核对已有 PRD、原型、设计、代码与证据，补齐当前阶段缺口后再申请推进。开发前对照批准原型和契约；实现偏差记录后交用户确认。
<!-- /harness-stage-deliverables -->
