# 阶段 3：发布前确认

执行前提：草稿已保存，每一轮的入队视图链接都已写入。

## 检查

`check_readiness(env, project_id)`。不传 config 时工具读取已保存的草稿。

- `summary.ready_to_publish=false` 时停下，把 level 为 `blocker` 的项逐条列给用户，说明要先修，
  修好后重新检查。
- `warning` 项不阻断，但要提醒用户留意。`unverified` 项不算通过，说明这一项查不到、需要用户
  自己确认，不要写成「已通过」。

## 发布前清单

`pre_publish_checklist(env, project_id)`。把 `checklist_markdown` 原样展示给用户。它包含两项
待确认：配置信息是否无误（附配置页链接和草稿保存时间）、工作流配置是否无误（列出发布后会创建
的工作流及监听的列）。模版二会提示「审核操作」工作流需要人工修补。

如果返回里有 `blockers`，把清单给用户看的同时说明这些必须先处理，不要询问是否发布。

## 发布

用户明确确认后（例如回复「确认发布」），调用：

```
publish(env, project_id, config, base_version, confirm=true, confirm_project_id=project_id)
```

- `config` 取 `get_editor` 返回的 `draft.config`，不要重新组装。
- `base_version` 取 `pre_publish_checklist` 返回的 `base_version`；从未发布时是 0。
- 生产环境必须传 `confirm_project_id`。
- 先按写操作规则展示一次预览（`confirm=false`），确认后才执行。用户已在清单阶段确认过配置内容时，
  仍然要把这次发布的目标环境、项目和配置版本说清楚再执行。

返回 `conflict` 时不强行覆盖：重新 `get_editor` 读取最新 `published_version` 和草稿，说明
版本已被他人更新，请用户重新确认后再发布。

发布成功后记下返回的 `version` 和 `published_at`。

## 写入进度

```json
{"stage": 3, "status": "done", "published_version": 1, "published_at": "...",
 "checklist_confirmed": true}
```
