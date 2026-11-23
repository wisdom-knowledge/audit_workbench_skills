# 版本说明

版本号同时写在 `.claude-plugin/plugin.json`、`.codex-plugin/plugin.json` 和
`audit_workbench_mcp/pyproject.toml`，三处保持一致，`check_setup` 返回的就是这个版本。

## 1.0.0

首个插件版本，一次安装入口技能、五个子技能和管理端 MCP。

- 入口 `audit-workbench`：定位环境和项目，按目标分发到接入、改配置、工作流、审核员、排障。
- 接入：推荐配置、发布前清单、工作流同步与启用、审核员绑定，可从线上状态续接（`onboard_status`）。
- 排障：`trace` 按 record_id 沿依赖链给出卡点；提交后判断结合审核日志、`task_submit` 事件和飞书当前值，
  结论待定时用 aliyun CLI 查 SLS 运行日志。
- 新增 `check_setup`：检查管理端登录态、lark-cli 用户身份和阿里云日志读权限，并返回版本。
- 不包含 `audit-workbench-enqueue-workflow`，它仍按原方式单独安装。
