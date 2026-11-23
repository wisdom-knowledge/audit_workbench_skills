# audit_workbench_skills

审核工作台 skills 集合。入口技能、五个子技能和管理端 MCP 打包成 `audit-workbench` 插件，放在
`plugin/` 下。

## Skills

| Skill | 用途 |
|---|---|
| [audit-workbench](plugin/skills/audit-workbench/SKILL.md) | 入口：定位项目，按目标分发到下面五个子技能 |
| [audit-workbench-onboard](plugin/skills/audit-workbench-onboard/SKILL.md) | 项目接入：配置推荐、发布、工作流启用、审核员绑定与交付 |
| [audit-workbench-config](plugin/skills/audit-workbench-config/SKILL.md) | 修改已接入项目的配置并发布，放弃草稿，暂停或恢复 |
| [audit-workbench-workflow](plugin/skills/audit-workbench-workflow/SKILL.md) | 查工作流同步状态、重试失败轮次、模版二人工修补、启用 |
| [audit-workbench-auditors](plugin/skills/audit-workbench-auditors/SKILL.md) | 增删审核员，检查飞书账号绑定 |
| [audit-workbench-ops](plugin/skills/audit-workbench-ops/SKILL.md) | 按 record_id 排查记录为什么没进专家端、提交后飞书为什么没变 |

## 安装插件

插件一次装好六个技能和 `audit-workbench` MCP，不需要再手工注册 MCP。仓库是私有的，本机要能用 SSH
或已登录的 `gh` 访问 GitHub。

| 客户端 | 安装 | 更新 |
|---|---|---|
| Claude Code | `claude plugin marketplace add wisdom-knowledge/audit_workbench_skills`，然后 `claude plugin install audit-workbench@audit-workbench` | `claude plugin marketplace update audit-workbench`，再 `claude plugin update audit-workbench@audit-workbench`；重启后生效 |
| Codex | `codex plugin marketplace add wisdom-knowledge/audit_workbench_skills --ref main`，然后 `codex plugin add audit-workbench@audit-workbench` | `codex plugin marketplace upgrade audit-workbench`；必要时重启 |

Claude Code 里也可以直接：

```text
/plugin install audit-workbench --marketplace wisdom-knowledge/audit_workbench_skills
```

装好后在新对话里说要做的事（例如「给项目 123 接入审核工作台」）。第一次用某个环境时，技能会先调用
`check_setup` 做授权检查，按结果补齐登录或授权。

### 依赖

| 依赖 | 是否必需 | 用途 |
|-|-|-|
| [uv](https://docs.astral.sh/uv/) | 必需 | 启动 MCP，Python 由 uv 自动准备 |
| 管理端登录态 | 必需 | 调管理端接口；没有时 `login` 工具弹出登录页 |
| `lark-cli`，用户身份已登录 | 必需 | 设协作者、读字段分组、读写工作流启用状态 |
| `aliyun` CLI，有日志读权限 | 可选 | 排障时查后端运行日志；没有时这一步标「未核验」 |

### 从旧的软链安装迁移

以前用 `install.py` 软链到 `~/.agents/skills/` 并手工注册 MCP 的，装插件后会出现两份技能和两个
MCP。确认插件可用后再清理旧的：删掉 `~/.agents/skills/` 等目录里指向本仓库的 `audit-workbench*`
软链，并移除手工注册的 MCP，例如
`claude mcp remove audit-workbench`。不要删本仓库。

## 发布新版本

1. 改代码或技能后，同步修改三处版本号：`plugin/.claude-plugin/plugin.json`、
   `plugin/.codex-plugin/plugin.json`、`plugin/audit_workbench_mcp/pyproject.toml`。
2. 在 [plugin/CHANGELOG.md](plugin/CHANGELOG.md) 写这一版改了什么。
3. 跑测试，合入 `main`。使用者按上表的更新命令拿到新版。

```bash
cd plugin/audit_workbench_mcp && uv run pytest
python3 ../skills/audit-workbench/scripts/test_skills.py
claude plugin validate ../..
```

插件目录里的技能和 MCP 必须是实体文件：Codex 安装时不跟随软链。

## 开发者本地安装

改技能想立即生效、不经过插件缓存时，用软链安装，并按
[plugin/audit_workbench_mcp/README.md](plugin/audit_workbench_mcp/README.md) 手工注册 MCP。不要和插件同时装。

```bash
python3 plugin/skills/audit-workbench/scripts/install.py
```

## 已删除的 audit-workbench-enqueue-workflow

旧的 `audit-workbench-enqueue-workflow` skill 已删除：入队工作流现在由发布后的后端 Worker 创建，用插件里的
工作流子技能查看、重试和启用。以前装过它的，删掉 `~/.agents/skills/audit-workbench-enqueue-workflow`
以及其他客户端 skills 目录里指向它的软链即可。它的 fetch-on-use 入口会从 GitHub `main` 拉正文，
删除合入 `main` 后入口就拉不到内容了。
