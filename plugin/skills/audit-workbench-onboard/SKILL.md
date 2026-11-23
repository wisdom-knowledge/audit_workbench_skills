---
name: audit-workbench-onboard
description: >
  给一个项目接入审核工作台：从环境、项目 ID 和底表链接开始，完成字段推荐、草稿保存、发布前确认、
  工作流启用和审核员绑定，最后交付配置页与待办。用于新项目接入、已有项目重新走一遍接入，或接入
  中途中断后继续。不要用于已接入项目的配置微调，或单独查工作流、审核员。
metadata:
  requires:
    bins: ["lark-cli"]
    skills: ["lark-base"]
---

# 接入

先读 [通用规则](../audit-workbench/references/rules.md)。环境和项目 ID 按入口的「定位项目」取得；
接入还需要底表链接，缺了只问这一项。

## 执行规则

1. 六个阶段按顺序走。每个阶段动手前，先完整读完该阶段的参考文件再执行；markdown 链接不等于
   已经读过。
2. 不写本地进度文件。同一会话里接着做时沿用上下文；新会话或上下文里找不到进度时，按
   [续接](references/resume.md) 从线上状态判断当前阶段。
3. 用户说「先到这」时停下，说明当前停在哪个阶段、恢复时说「继续」即可，不要提前做后面的阶段。

## 阶段

| 阶段 | 进入条件 | 执行前完整读取 |
|-|-|-|
| 1 识别与初始化 | 有环境、项目 ID、底表链接 | [init.md](references/init.md) |
| 2 推荐配置（2.1 字段 → 2.2 映射 → 2.3 入队条件，逐步确认） | 初始化完成 | [alignment.md](references/alignment.md)、[draft.md](references/draft.md) |
| 3 发布前确认 | 草稿已保存，每轮入队视图都已写入 | [publish.md](../audit-workbench-config/references/publish.md) |
| 4 工作流交接 | 发布完成 | [handoff.md](../audit-workbench-workflow/references/handoff.md) |
| 5 审核员 | 工作流全部启用 | [审核员](../audit-workbench-auditors/SKILL.md) 的「添加」和「检查飞书绑定」 |
| 6 交付 | 审核员检查完成 | [report.md](references/report.md) |
| 续接 | 用户说「继续」「接着做」，或新会话恢复 | [resume.md](references/resume.md) |

## 失败就停

以下情况不往下走，只告诉用户缺什么、怎么补：没有参考项目可用；对齐表里出现底表不存在的字段；
发布前检查有阻断项；工作流同步失败或超时；模版二的人工修补没被回读确认；审核员一个都没加上。
