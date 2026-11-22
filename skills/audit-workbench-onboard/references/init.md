# 阶段 1：识别与初始化

执行前确认三个输入齐全：环境（boe / prod）、项目 ID（正整数）、底表链接。缺哪个只问哪个，都缺时
发一句：「请提供环境（boe / prod）、项目 ID 和飞书底表链接。」其余信息从工具读取，不重复问。

## 调用顺序

1. `get_editor(env, project_id)`。记录它在 `summary` 里返回的 `published_version`、
   `draft_updated_at`、`runtime_status`。如果已有草稿，记下它的存在；已有草稿时阶段 2 的推荐
   会先返回预览，由用户确认是否覆盖。
2. `parse_feishu(env, table_url, project_id)`。传项目 ID，后端会同时更新该项目的字段目录。
   记下返回的 `app_token`、`table_id` 和 `fields`，它们是后续所有步骤的底表事实。
3. `ensure_app_collaborator(env, app_token)`。用 lark-cli 以用户身份把「人才招聘」设为底表
   可管理协作者。返回 `action` 是 `present` / `added` / `upgraded`，用一句话告诉用户结果。
   返回 `ok=false` 时停下，说明原因：通常是你本人对这张底表没有管理权限，需要先取得权限。
   发布时后端 Worker 用这个应用的身份建工作流，所以这一步必须在推荐配置之前完成。
4. `get_field_groups(env, app_token, table_id)`。读取当前底表的字段分组。`ok=true` 时记下
   分组名和字段 ID，供阶段 2 判断轮次和缩小角色字段的候选范围。`ok=false` 或 `groups` 为空时
   不停下，记下原因，阶段 2 退回到只按字段名判断，并把相关推荐的 `basis` 降为 `semantic`。

不要在初始化阶段调用 `publish`、`save_draft`、`enable_workflows` 等写操作。

## 模版类型

模板类型取 `get_editor` 里草稿或已发布配置的 `workbenchType`。取不到时问用户用模版一还是模版二。
模版一是审核状态下拉选择，模版二是打回/通过/拒绝按钮。这个值贯穿阶段 2 到阶段 4。

## 写入进度

```json
{"stage": 1, "status": "done", "env": "boe", "project_id": 1234,
 "table_url": "...", "app_token": "...", "table_id": "...",
 "workbench_type": 1, "field_groups_ok": true, "collaborator": "added",
 "published_version": 0, "draft_updated_at": null}
```
