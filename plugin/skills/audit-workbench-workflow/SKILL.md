---
name: audit-workbench-workflow
description: >
  处理审核工作台发布后在飞书上生成的工作流：查各轮同步状态、重试失败的轮次、确认模版二审核操作
  工作流的人工修补、启用工作流。不要用于改配置或在飞书上手工新建入队工作流。
---

# 工作流

先读 [通用规则](../audit-workbench/references/rules.md)。环境和项目 ID 按入口的「定位项目」取得。

工作流由后端 Worker 按已发布配置创建和更新，这里不在飞书上手工建。项目没有已发布版本时没有工作流可查，告诉用户先发布。

## 按目标处理

| 用户要什么 | 做什么 |
|-|-|
| 刚发布完，或要确认工作流能不能启用 | 按 [发布后交接](references/handoff.md) 走完：等同步、人工修补、启用 |
| 只看现在各轮的同步状态 | `get_workflows`，按下面的状态说明逐条讲，`problems` 逐条转述 |
| 某一轮同步失败 | 先看 `lastError` 说明原因，能修的先修，再按下面「重试」只重试那一轮 |
| 模版二修补完了 | `created_workflows` 回读，`repaired=true` 才算修好，然后启用 |

## 同步状态

`display_status` 的含义：`pending` 排队中；`running` 同步中；`retrying` 失败后等待自动重试；
`synced` 已同步；`failed` 已到重试上限，要手动重试；`manual` 配置有变化，但这条工作流人工修补
过，没有被自动覆盖。

Worker 每条最多自动尝试 5 次，第 n 次失败后等 3n 秒再试。手动重试会把计数清零。

## 重试

`retry_workflows(env, project_id, stages, kind)`。`stages` 只填出错的轮次，`kind` 填出错的
种类（`ENQUEUE` 入队、`AUDIT_ACTION` 审核操作），不要不加限制地全部重试。先预览，同意后带
`confirm=true`。重试后调用 `wait_workflows` 等结果，`timed_out=true` 只表示还没完成，不代表成功。

`manual` 状态有两种处理，让用户选：

- 在飞书上按新的列名手工改这条工作流，改完后用 `get_workflows` 再查一次。
- `force_update=true` 重试，用新配置覆盖。人工补过的步骤会丢，模版二的审核操作工作流要重新修补。
  预览时把这个后果说清楚。
