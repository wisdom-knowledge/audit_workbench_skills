---
name: audit-workbench-onboard
description: >
  给一个项目接入审核工作台：从环境、项目 ID 和底表链接开始，完成字段推荐、草稿保存、发布前确认、
  工作流启用和审核员绑定，最后交付配置页与待办。用于新项目接入或已有项目重新走一遍接入流程。
  不要用于单独创建飞书工作流、单独查一个状态，或不涉及接入的配置微调。
metadata:
  requires:
    bins: ["lark-cli", "python3"]
    skills: ["lark-base"]
---

# 审核工作台项目接入

输入是环境（boe / prod）、项目 ID、底表链接。工具全部来自 `audit-workbench` MCP，另一个
`audit-workbench-enqueue-workflow` skill 不参与本流程，也不要调用它的脚本。

对用户说话要短。工具返回的 `report_markdown`、`checklist_markdown`、`workflows_markdown`、
`binding_markdown` 一律原样展示，不改写、不总结、不补解释。用户没问的内容不主动展开。

## 执行规则

1. 六个阶段按顺序走。每阶段动手前，先完整读取该阶段 `references/` 下的文件，读完再执行；
   markdown 链接不等于已加载。
2. 每阶段把进度写进工作区的 `progress.json`，格式见 [references/resume.md](references/resume.md)。
   续接时先读进度，再回读线上状态；两者不一致时以线上为准并说明差异。
3. 写操作默认只返回预览。把预览给用户看，得到确认后才带 `confirm=true` 再调用。生产环境还要传
   `confirm_project_id`，值与 `project_id` 相同。用户主动给出的入队视图链接、审核员 talent_id，
   视为已确认，可直接写入。
4. 返回 `unauthorized` 时调用 `login`；返回 `conflict` 时先 `get_editor` 重新读取，不强行覆盖。
5. 遇到底表缺列、权限不足、版本冲突、接口失败时停下，只说明原因和下一步，不猜测补齐、不跳过阶段。
6. 工具报 `ok=false` 时把原因原样转述，不要重试同一调用超过一次。

## 阶段路由

| 阶段 | 触发 | 执行前完整读取 |
|-|-|-|
| 1 识别与初始化 | 用户提供项目与底表后 | [references/init.md](references/init.md) |
| 2 推荐配置 | 初始化完成 | [references/alignment.md](references/alignment.md)、[references/draft.md](references/draft.md) |
| 3 发布前确认 | 草稿已保存，入队视图已写入 | [references/publish.md](references/publish.md) |
| 4 工作流交接 | 发布完成 | [references/handoff.md](references/handoff.md) |
| 5 审核员 | 工作流启用完成 | [references/auditors.md](references/auditors.md) |
| 6 交付 | 审核员检查完成 | [references/report.md](references/report.md) |
| 续接 | 用户说「继续」「接着做」，或新会话恢复 | [references/resume.md](references/resume.md) |

每个阶段结束时把结果写进 `progress.json`，再进入下一阶段。用户说「先到这」时停下并说明当前阶段
与恢复入口，不要提前执行后面的阶段。

## 失败就停

以下情况不继续往下走，只告诉用户缺什么、怎么补：没有参考项目可用；对齐表里出现底表不存在的字段；
发布前检查有阻断项；工作流同步失败或超时；模版二的人工修补没被回读确认；审核员 talent_id 找不到。
