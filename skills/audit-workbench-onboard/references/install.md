# 安装

这个 skill 不依赖 `audit-workbench-enqueue-workflow`，也不从 GitHub 拉正文。安装脚本把完整目录
软链到 `~/.agents/skills/audit-workbench-onboard`，再给其他客户端的 skills 目录建软链。改仓库里的
文件立刻生效，不需要重新安装。

```bash
python3 skills/audit-workbench-onboard/scripts/install.py
```

先看会改哪些路径：

```bash
python3 skills/audit-workbench-onboard/scripts/install.py --dry-run
```

## 前提

- `audit-workbench` MCP 已在本机注册并可用。安装方式见仓库里 `audit_workbench_mcp/README.md`。
- `lark-cli` 已安装，且当前用户已登录；MCP 在设置协作者、读工作流、启停工作流时都以用户身份
  调用它。
- 使用者对目标底表有管理权限，否则 `ensure_app_collaborator` 会失败。
- 有对应环境的管理员登录态，供 MCP 调用管理端接口。登录态失效时 MCP 返回 `unauthorized`，
  由 `login` 工具重新登录。

## 触发

给出环境、项目 ID 和底表链接，并说明要接入审核工作台；或直接点名
`$audit-workbench-onboard`。缺少输入时 skill 只问缺的那几项。

## 检查安装

```bash
ls -l ~/.agents/skills/audit-workbench-onboard
ls ~/.agents/skills/audit-workbench-onboard/references
```
