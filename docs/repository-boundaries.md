# 脚手架与实验仓库

- `he_skeleton` 维护 Harness 脚本、工作流、同步工具和通用测试。业务 Issue 自动执行工作流在此仓库保持停用。
- `reading_list` 提实验 Issue，保存业务分支、PR 和预览。当前阶段验证静态网页闭环，不代表真实后端开发已经支持。
- 两者使用不同 Runner 工作区和 Session 目录。旧本地待办网页不是 业务项目 的交付物，不用它冒充实验成功。

## 同步经过提交的版本

在脚手架仓库执行：

```sh
python3 scripts/sync_project.py <product-checkout> --ref <harness-commit>
```

同步只覆盖明确列出的 Harness 文件，不覆盖业务 `app/`、实验说明或业务提交；若 业务项目 修改了托管文件，会拒绝覆盖。`harness-upstream.json` 记录提交和文件校验值。检查 业务项目 diff、提交并推送后，才用新版本运行实验。

修复发生在脚手架仓库，验证发生在实验仓库。实验发现问题须回到脚手架修复，不能只改 业务项目 留下两个版本。

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

脚本下载上游提交，运行测试，创建或更新业务测试分支，只同步托管文件。默认上游 ref 为 main。目标分支首次从业务默认分支创建，后续只追加提交；业务 app 不覆盖，托管文件有自行修改则停止。不创建升级 PR，不更新任何一边的 main。

发现问题回源仓库修复，再运行相同命令更新同一测试分支。重复运行该分支会保留它自己的 Session；换测试分支会开启独立 Session。可省略 --run 只同步，或在 GitHub Actions 的 Run workflow 中选择该测试分支继续反馈。同一个 Issue 可被不同测试分支使用；评论里的 /harness 仍属于主线入口，不用于继续分支实验。

测试分支的 Agent 代码产出使用独立任务分支，Session 与预览写入该实验的目录。预览及截图上传到运行的 github-pages artifact，不部署主线 Pages；解压其中 artifact.tar 后打开对应页面即可检查。测试分支输入使用 Issue，不直接改已有 PR 分支。当前应用仍限静态网页。

上游验证通过后独立合并发布；业务主线何时升级另行决定。要求 gh 已登录且有目标仓库写权限，以及 Python、Git、Node。该命令按需运行，没有安装定时任务。
