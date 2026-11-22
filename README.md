# audit_workbench_skills

审核工作台 skills 集合。每个 skill 在 `skills/<name>/` 下独立维护。

## Skills

| Skill | 用途 |
|---|---|
| [audit-workbench-onboard](skills/audit-workbench-onboard/SKILL.md) | 项目接入审核工作台：配置推荐、发布、工作流启用、审核员绑定与交付 |
| [audit-workbench-enqueue-workflow](skills/audit-workbench-enqueue-workflow/SKILL.md) | 在飞书多维表格上按轮创建审核工作台入队工作流 |

`audit-workbench-onboard` 不依赖 enqueue-workflow skill，也不会调用它的脚本。

## 安装

两个 skill 各自独立安装。

`audit-workbench-onboard` 直接把完整目录软链到本机，改仓库立即生效；它还需要本机注册了
`audit-workbench` MCP，见 [audit_workbench_mcp/README.md](audit_workbench_mcp/README.md)。

```bash
python3 skills/audit-workbench-onboard/scripts/install.py
```

`audit-workbench-enqueue-workflow` 装的是 fetch-on-use 入口，每次用会从 GitHub `main` 拉最新正文：

```bash
git clone git@github.com:wisdom-knowledge/audit_workbench_skills.git
python3 skills/audit-workbench-enqueue-workflow/scripts/install.py
```

开发者把 enqueue skill 链到本仓库（不拉远程）：

```bash
python3 skills/audit-workbench-enqueue-workflow/scripts/install.py --local
```

安装后下一轮对话再生效。API Key 只放本机 `~/.agents/secrets/`，不要写入仓库。

## 如何触发

在 Claude / Codex / Grok 等对话里，下面任意一种即可：

```text
$audit-workbench-enqueue-workflow
https://meetchances.feishu.cn/base/.....
```

```text
给这个表格创建审核工作台入队工作流
https://meetchances.feishu.cn/base/.....
```

点名 skill，或把飞书底表 URL 和「入队工作流」放在同一句，agent 会自动匹配。
