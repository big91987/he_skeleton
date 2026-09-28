# 脚手架与实验仓库

- `he_skeleton` 维护 Harness 脚本、工作流模板、同步工具和通用测试。业务工作流模板放在 templates/，源仓库不注册该业务工作流。
- `reading_list` 提实验 Issue，保存业务分支、PR 和预览。当前阶段验证静态网页闭环，不代表真实后端开发已经支持。
- 两者使用不同 Runner 工作区和 Session 目录。旧本地待办网页不是 业务项目 的交付物，不用它冒充实验成功。

## 同步经过提交的版本

在脚手架仓库执行：

```sh
python3 scripts/sync_project.py <product-checkout> --ref <harness-commit>
```

同步只覆盖明确列出的 `harness/` 工具文件，不覆盖业务代码。Workflow 和 Issue 表单仅首次安装时补齐不存在的文件，此后归 Owner 维护，不覆盖、不因删除而重建；旧版清单中的模板自动解除托管。工具文件有本地修改仍拒绝覆盖。`harness-upstream.json` 记录提交和文件校验值。检查 业务项目 diff、提交并推送后，才用新版本运行实验。

修复发生在脚手架仓库，验证发生在实验仓库。通用机制缺陷回脚手架修复；项目专属编排由业务仓库 Owner 修改，不要求回源仓库。

## 一次接入一个业务仓库

先创建具体产品仓库，再从脚手架目录执行：

```sh
python3 scripts/bootstrap_project.py <owner>/<product> --directory <product-checkout> --ref <harness-commit> --activate
```

当前入口面向 macOS ARM64、本机已登录 gh/Codex、公开实验项目的 main 分支。它准备受管理文件、提交推送、配置任务标签和 Pages、安装校验过的 Runner、浏览器依赖并注册启动服务。没有 `--activate` 时只准备文件。不会修改已有 app/。

一键接入不等于业务验收通过；仍须在该产品仓库完成实际 Issue→反馈→预览验证。目前应用执行器仍以静态网页验证为范围，后端项目配置尚待扩展。

## 在业务测试分支验证源仓库修复

机制问题只在 he_skeleton 修复并提交。然后从脚手架目录执行：

```sh
python3 scripts/update_project.py <owner>/<product> \
  --ref <upstream-branch-or-sha> \
  --branch codex/harness-test-<scenario> \
  --run --task <issue-number> --instruction 'clarify 检查需求并提出必要问题'
```

脚本下载上游提交，运行测试，创建或更新业务测试分支，升级仅同步工具文件并迁移清单，保留项目 Workflow 和表单。默认上游 ref 为 main。目标分支首次从业务默认分支创建，后续只追加提交；业务 app 不覆盖，托管文件有自行修改则停止。不创建升级 PR，不更新任何一边的 main。

发现问题回源仓库修复，再运行相同命令更新同一测试分支。重复运行该分支会保留它自己的 Session；换测试分支会开启独立 Session。可省略 --run 只同步，或在 GitHub Actions 的 Run workflow 中选择该测试分支继续反馈。同一个 Issue 可被不同测试分支使用；评论里的 /harness 仍属于主线入口，不用于继续分支实验。

测试分支的 Agent 代码产出使用独立任务分支，Session 与预览写入该实验的目录。截图、报告和静态产物按 main/ 与 experiments/<scope>/ 隔离路径统一托管。工作流发布前打包保留的各实验材料，发布成功后验证公开地址，再在 Issue 和关联开放 PR 中更新同一张交付卡片。网页类型额外提供应用入口；卡片本身不要求产品必须是网页。测试分支输入使用 Issue，不直接改已有 PR 分支。当前自动验证器仍限静态网页；其他产品可生成代码和文档，但未接入验证器时保持待验证。

上游验证通过后独立合并发布；业务主线何时升级另行决定。要求 gh 已登录且有目标仓库写权限，以及 Python、Git、Node。该命令按需运行，没有安装定时任务。

## 证据展示的当前边界

卡片标明代码提交、真实运行、自动检查结果及人工验收状态；截图直接嵌入评论，无需下载附件。当前生产证据的执行器仍是静态网页浏览器检查，CLI/桌面应用等证据采集尚未实现。证据托管使用 GitHub Pages，因此当前公开实验项目的材料可公开访问；不能直接用于内部敏感材料。Issue 评论继续测试分支的路由仍待实现，不把发布展示成功当作完整需求反馈闭环。

Workflow 定制、模板差异和升级边界见 [Workflow 所有权](workflow-ownership.md)。
