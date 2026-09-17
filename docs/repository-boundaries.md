# 脚手架与实验仓库

- `he_skeleton` 维护 Harness 脚本、工作流、同步工具和通用测试。业务 Issue 自动执行工作流在此仓库保持停用。
- `he_skeleton_lab` 提实验 Issue，保存业务分支、PR 和预览。当前阶段验证静态网页闭环，不代表真实后端开发已经支持。
- 两者使用不同 Runner 工作区和 Session 目录。旧本地待办网页不是 lab 的交付物，不用它冒充实验成功。

## 同步经过提交的版本

在脚手架仓库执行：

```sh
python3 scripts/sync_lab.py <lab-checkout> --ref <harness-commit>
```

同步只覆盖明确列出的 Harness 文件，不覆盖业务 `app/`、实验说明或业务提交；若 lab 修改了托管文件，会拒绝覆盖。`harness-upstream.json` 记录提交和文件校验值。检查 lab diff、提交并推送后，才用新版本运行实验。

修复发生在脚手架仓库，验证发生在实验仓库。实验发现问题须回到脚手架修复，不能只改 lab 留下两个版本。
