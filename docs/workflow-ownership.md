# Workflow 由项目 Owner 维护

## 文件边界

| 源仓库内容 | 业务仓库位置 | 更新方式 |
| --- | --- | --- |
| harness/ 中列入同步清单的执行工具 | harness/ | 按固定提交升级，检测本地修改，冲突则停止 |
| templates/.github/workflows/harness.yml | .github/workflows/harness.yml | 首次安装时缺失才复制，之后 Owner 自行调整 |
| templates/.github/ISSUE_TEMPLATE/task.yml | .github/ISSUE_TEMPLATE/task.yml | 同上 |
| 项目的 harness-project.json | 项目根目录 | 项目自行维护，工具同步不覆盖 |

现有模板是基础研发流程，内部为 work → publish → record；尚未实现 PRD、设计、开发、验收分阶段的完整流程。loop.py 仍包含任务循环，不能宣称当前已能任意组合内部阶段。

首次安装以不存在 harness-upstream.json 判断。已有同名 Workflow 或表单时保留原文件；安装后即使 Owner 重命名或删除文件，后续升级也不重新创建。旧版清单曾把 Workflow、表单列为托管文件，升级时会移除这些条目，保留项目文件现状，包括本地修改。新版清单的 revision 仅说明工具版本，不表示项目 Workflow 与同版本模板一致。

## Owner 怎么定制

直接在业务仓库修改 .github/workflows/harness.yml，按项目需要改触发事件、Job、Runner 标签、验证或发布步骤；也可重命名或新增其他 Workflow。修改后走业务仓库自己的审查流程。默认 Coding Agent 仍禁止修改 .github 和 Harness 控制文件，这不限制 Owner 在自己的分支上修改。

默认模板只接受 Issue、评论、手动事件；loop.py 也只处理它已支持的输入。增加任意 YAML 事件不等于 loop.py 自动支持该事件。现有默认权限仍为仓库所有者，本机执行仍要求指定 Runner。扩大事件或权限需同时调整并验证执行入口。多个 Workflow 订阅相同事件可能同时运行，Owner 应用条件明确区分。

## 查看上游模板差异

在源仓库执行下面命令，只打印差异，不写项目文件：

```sh
python3 scripts/sync_project.py <product-checkout> --ref <harness-commit> --template-diff
```

对远端实验分支也可以只读查看，不创建分支、不提交、不触发：

```sh
python3 scripts/update_project.py <owner>/<product> --ref <harness-commit> \
  --branch codex/harness-test-<scenario> --template-diff
```

差异左侧是项目当前文件，右侧是上游模板；删除/重命名后的默认路径会显示为缺失，不表示必须恢复。Owner 挑选需要的改动手工合入自己的 Workflow，不自动整文件替换。

## 工具升级和验证

正常 sync_project.py / update_project.py 命令只更新工具，不自动采纳模板变动。如果上游修复同时需要改 Workflow，先查看差异，再由 Owner 在测试分支应用相关变动、验证两者配合。不要把工具升级成功当成自定义 Workflow 兼容性通过。

update_project.py --run 默认 dispatch harness.yml。Owner 重命名后，可用 --workflow <filename.yml> 选择自己的 Workflow；该快捷入口要求它保留 workflow_dispatch 的 task、instruction 输入以及实验分支隔离约定。采用其他参数或分支规则的流程，请从 Actions 按项目自己的入口执行。

工具升级不自动变更项目流程，也不自动合并主线。当前初始化仍使用 macOS ARM64 Runner、公开实验仓库及 Pages 配置，尚不是任意环境的通用部署器。
