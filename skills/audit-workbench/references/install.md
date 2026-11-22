# 安装

入口 `audit-workbench` 和四个子技能（onboard、config、workflow、auditors）一起安装。子技能之间用
相对路径互相引用，只装其中一个会找不到共用的规则。

安装脚本把每个 skill 目录软链到 `~/.agents/skills/`，再给其他客户端的 skills 目录建软链。改仓库里
的文件立刻生效，不需要重新安装。不依赖 `audit-workbench-enqueue-workflow`，也不从 GitHub 拉正文。

```bash
python3 skills/audit-workbench/scripts/install.py
```

先看会改哪些路径：

```bash
python3 skills/audit-workbench/scripts/install.py --dry-run
```

## 前提

- `audit-workbench` MCP 已在本机注册并可用，安装方式见仓库里的 `audit_workbench_mcp/README.md`。
- `lark-cli` 已安装，当前用户已登录。MCP 在设置协作者、读字段分组、读写工作流状态时以用户身份
  调用它。
- 使用者对目标底表有管理权限，否则 `ensure_app_collaborator` 会失败。
- 有对应环境的管理员登录态。失效时 MCP 返回 `unauthorized`，由 `login` 工具重新登录。

## 检查安装

```bash
ls -l ~/.agents/skills/ | grep audit-workbench
```

应看到五个软链都指向本仓库的 `skills/` 下对应目录。安装后在新一轮对话里生效。
