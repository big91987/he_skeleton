# Project worker instructions

Read `docs/00-global/project.md` and the current task before working. Follow the product scope and existing code. Use the native stage Skills as needed, without copying their full text into prompts.

Communicate directly with the user: before working, briefly say which stage you are in and what you will do with their request. Share meaningful progress, findings or blockers as needed. Use commentary for these messages and reserve the three-field JSON for the final result. Tool calls stay in Actions logs; your progress messages accumulate in a collapsed Issue comment, followed by a separate final reply. Choose useful wording and timing instead of repeating a fixed status template.

Never fabricate verification or change managed execution rules. Fix reusable tools upstream. Run project checks and format/lint before declaring delivery. Keep credentials and private sessions out of Git.

See [the light workflow](docs/harness-light.md). Owner configuration: `.harness/full.json`.

When the owner configures `browser_roots`, design and development have the native `harness_browser.check` tool. Use it for real prototype/product browser checks instead of launching Chromium in the shell sandbox. Write a JSON action plan in the project and pass its path and an allowed application root to the tool. Inspect the returned results and screenshot files; include useful evidence in `artifacts`. A screenshot or a passing smoke plan does not replace the task's functional acceptance criteria. Fix failed checks and rerun the same tool; do not ask the user to supply screenshots because the shell sandbox cannot launch a browser.

<!-- harness-stage-deliverables -->
## 阶段产物与 Skill 入口

Requirements, design and development are three stage Agents with separate native Sessions and separate Jobs. Within a stage, resume its own Session and use its enabled native Skills. Share the project workspace and handoff documents across stages. The previous Agent's handoff includes the user's message and that Agent's conclusion; it is context, not a new request addressed to you.

Each stage Agent owns its conversation and follows its Skills: decide whether clarification, changes or human confirmation are needed, and interpret the user's reply in context. Requirements and design need human confirmation before handoff; do not approve on the user's behalf. Decide whether a change affects an already confirmed decision rather than asking again merely because evidence or explanatory files were updated. Record product decisions in the existing task documents so the next Agent can continue. The framework records your decision and routes the next Job; it does not interpret approval by keywords, file hashes or comment timestamps.

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
- 在 `artifacts` 列出供本次审查的真实文件集合（包括原型运行依赖及证据），回复中说明已完成什么、还缺什么、需要用户确认什么。让用户能审查方案及其引用材料，由阶段 Agent 结合对话判断确认范围。普通问答无需重复提交整包。
- 中途接入时先核对已有 PRD、原型、设计、代码与证据，补齐当前阶段缺口后再申请推进。开发前对照批准原型和契约；实现偏差记录后交用户确认。
<!-- /harness-stage-deliverables -->
