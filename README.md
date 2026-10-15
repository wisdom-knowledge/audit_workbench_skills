# audit_workbench_skills

审核工作台 skills 集合。每个 skill 在 `skills/<name>/` 下独立维护。

## Skills

| Skill | 用途 |
|---|---|
| [audit-workbench-enqueue-workflow](skills/audit-workbench-enqueue-workflow/SKILL.md) | 在飞书多维表格上按轮创建审核工作台入队工作流 |

## 安装

```bash
git clone git@github.com:wisdom-knowledge/audit_workbench_skills.git
python3 skills/audit-workbench-enqueue-workflow/scripts/install.py
```

API Key 只放本机 `~/.agents/secrets/`，不要写入仓库。
