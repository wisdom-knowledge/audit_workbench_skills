---
name: audit-workbench-auditors
description: >
  管理审核工作台项目的审核员：按 talent_id 添加或移除审核员，查名单，检查审核员是否已绑定飞书
  账号并提醒未绑定的人去专家端绑定。不要用于改配置或处理工作流。
---

# 审核员

先读 [通用规则](../audit-workbench/references/rules.md)。环境和项目 ID 按入口的「定位项目」取得。

## 只接受 talent_id

增删审核员只按 talent_id。用户给的是姓名或手机号时，请用户提供对应的 talent_id，不要自己查表
匹配。查名单时可以按姓名模糊筛：`list_auditors(env, project_id, talent_name=...)`。

## 添加

`add_auditors(env, project_id, talent_ids)`。先预览，同意后带 `confirm=true`；生产环境另传
`confirm_project_id`。

返回里 `added` 和 `skipped` 都要告诉用户：已在名单中的会被跳过，不存在的 talent_id 会在
`skipped` 里给出原因。一个都没加上时停下，请用户核对 talent_id，不要继续检查绑定。

## 移除

`remove_auditors(env, project_id, talent_ids)`，是软删，不改任务。先预览，同意后带
`confirm=true`。返回里 `needs_reassign=true` 时，按 `removed` 里每人的 `pending_count` 告诉用户
这些人还有多少条没审完；这些任务不会自动转给别人，要在底表上改审核人。

## 检查飞书绑定

添加完成后，或用户问谁没绑定时，调用 `check_auditor_binding(env, project_id, talent_ids)`。
不传 `talent_ids` 时查全部启用中的审核员。把 `binding_markdown` 原样展示给用户。

结果分三类：

- `BOUND` 已绑定，列出飞书账号名。
- `UNBOUND` 未绑定，输出里用 🔴 标出。必须明确提醒用户：**通知这些审核员在专家端自行完成飞书
  账号绑定**。这件事要用户去做，不要替用户发消息，也不要说成已经绑定。
- `UNVERIFIED` 读绑定表失败，无法判断。单独说明，建议稍后重试，不要当成未绑定，否则已绑定的
  审核员会被误催。

这一步只负责查出来并提醒，工具不会替任何人绑定。
