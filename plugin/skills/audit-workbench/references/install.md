# 安装

入口 `audit-workbench`、五个子技能（onboard、config、workflow、auditors、ops）和 `audit-workbench`
MCP 打包在同一个插件里，一起安装。子技能之间用相对路径互相引用，只装其中一个会找不到共用的规则。

## 插件安装

| 客户端 | 安装 | 更新 |
|-|-|-|
| Claude Code | `claude plugin marketplace add wisdom-knowledge/audit_workbench_skills`，然后 `claude plugin install audit-workbench@audit-workbench` | `claude plugin marketplace update audit-workbench`，再 `claude plugin update audit-workbench@audit-workbench`，重启生效 |
| Codex | `codex plugin marketplace add wisdom-knowledge/audit_workbench_skills --ref main`，然后 `codex plugin add audit-workbench@audit-workbench` | `codex plugin marketplace upgrade audit-workbench` |

插件管理器负责更新，技能里不执行 Git，也不替用户装插件。用户问怎么装、怎么更新时，给出上表的命令。

## 前提

- `uv` 已安装，MCP 由它启动。
- `lark-cli` 已安装，当前用户已登录。MCP 在设置协作者、读字段分组、读写工作流状态时以用户身份
  调用它。
- 使用者对目标底表有管理权限，否则 `ensure_app_collaborator` 会失败。
- 有对应环境的管理员登录态。失效时 MCP 返回 `unauthorized`，由 `login` 工具重新登录。
- 可选：`aliyun` CLI 已配置，且对日志服务 project `k8s-log-c32adc70c4c89414982ad277c336722a5` 有读权限
  （`AliyunLogReadOnlyAccess` 即可）。排障时 `trace` 用它查后端运行日志；没有时这一步标「未核验」，
  其他功能不受影响。

`check_setup(env)` 会逐项检查这些前提，并返回插件版本。

## 开发者本地安装

改仓库想立即生效时，用软链安装，并按 `plugin/audit_workbench_mcp/README.md` 手工注册 MCP。
不要和插件同时装，否则会出现两份技能和两个 MCP。

```bash
python3 plugin/skills/audit-workbench/scripts/install.py
python3 plugin/skills/audit-workbench/scripts/install.py --dry-run   # 先看会改哪些路径
```
