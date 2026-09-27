# Project document index

Start with [project context](00-global/project.md). Record confirmed current behavior and unresolved decisions separately. Inspect code before assuming that a planned feature exists.

| Location | Shared content |
|---|---|
| `00-global/` | Project purpose, vocabulary, product boundaries and decisions |
| `01-architecture/tasks/<issue>/` | HLD, LLD, API/data contracts and architecture decisions |
| `02-research/` | Research evidence, not automatically accepted direction |
| `03-backlog/` | Future work outside the active commitment |
| `04-implementation/tasks/<issue>/` | PRD/AC, runnable `prototype/`, `design/README.md` artifact index and execution plan |
| `05-validation/tasks/<issue>/` | Verification scope, evidence and limitations |

Task paths are configured in `.harness/full.json`. Existing projects can point it to their existing indexes and stage documents; do not create a second competing source of truth.

See [full workflow](harness-full.md).

阶段交付物与 Skill 入口见 [AGENTS.md](../AGENTS.md)。设计索引链接完整审查集合，不替代各项产物。已有路径通过本索引映射，复用规则和裁剪确认同样适用。
