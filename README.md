# audit_workbench_skills

审核工作台 skills 集合。每个 skill 在 `skills/<name>/` 下独立维护。

## Skills

| Skill | 用途 |
|---|---|
| [audit-workbench-enqueue-workflow](skills/audit-workbench-enqueue-workflow/SKILL.md) | 在飞书多维表格上按轮创建审核工作台入队工作流 |

## 安装

本机只装入口。之后每次用 skill 都会从 GitHub `main` 拉最新正文，不必再 `git pull`。

```bash
git clone git@github.com:wisdom-knowledge/audit_workbench_skills.git
python3 skills/audit-workbench-enqueue-workflow/scripts/install.py
```

已装过旧版的人再跑一次 `install.py` 换成入口。安装后下一轮对话再生效。API Key 只放本机 `~/.agents/secrets/`，不要写入仓库。

开发者链到本仓库（不拉远程）：

```bash
python3 skills/audit-workbench-enqueue-workflow/scripts/install.py --local
```

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
