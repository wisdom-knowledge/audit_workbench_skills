---
name: audit-workbench-enqueue-workflow
description: >
  为某个项目的审核工作台在飞书多维表格上创建入队工作流。用户给底表 URL、确认轮次后，按轮生成
  SetRecordTrigger → enqueue HTTP；非末轮带晋级兜底。不要用于建表、发布 schema、submit/晋级代码，或非入队自动化。
metadata:
  requires:
    bins: ["lark-cli", "git", "python3"]
    skills: ["lark-base"]
---

# 审核工作台入队工作流（入口）

本目录只是入口。流程、references、渲染脚本以 GitHub `main` 为准。

动手前先同步，然后 **只按缓存里的 SKILL.md 执行**。不要用这份入口继续做业务步骤，也不要向用户解释同步过程。

```bash
python3 ~/.agents/skills/audit-workbench-enqueue-workflow/scripts/sync_from_github.py
```

stdout 含 `skill_dir=<绝对路径>`。接着：

1. Read `<skill_dir>/SKILL.md`
2. 按那份正文执行（references、scripts 都用 `<skill_dir>` 下的）
3. `ok=true`：用刚拉到的版本
4. `ok=false` 但仍有 `skill_dir`：用缓存里的上一份
5. 没有 `skill_dir`：停下，只说拉不到最新 skill

仓库：`git@github.com:wisdom-knowledge/audit_workbench_skills.git`  
skill 路径：`skills/audit-workbench-enqueue-workflow`
