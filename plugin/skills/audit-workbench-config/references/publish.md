# 发布

执行前提：草稿已保存，每一轮的入队视图链接都不为空。有轮次为空时先补，否则发布会因视图解析失败
被拒绝，或发布后该轮不会入队。

## 配置校验

`check_readiness(env, project_id)`。不传 config 时工具读取已保存的草稿。它只调后端发布预检，
`errors`（发布会失败）和 `workflowErrors`（工作流建不出来）都记为 `blocker`。

- `summary.ready_to_publish=false` 时停下，把每条 `blocker` 逐条列给用户，说明要先修，修好后
  重新检查。
- 审核员、底表依赖、人才招聘协作者和工作流创建不在这里查，发布后按「全链路校验」做。

## 发布前清单

`pre_publish_checklist(env, project_id)`。把 `checklist_markdown` 原样展示给用户。它包含两项
待确认：配置信息是否无误（附配置页链接和草稿保存时间）、工作流配置是否无误（列出发布后会创建
的工作流及监听的列）。模版二会提示「审核操作」工作流需要人工修补。

返回里有 `blockers` 时，展示清单的同时说明这些必须先处理，不要询问是否发布。

## 发布

用户明确确认后（例如回复「确认发布」）调用：

```
publish(env, project_id, config, base_version, confirm=true, confirm_project_id=project_id)
```

- `config` 取 `get_editor` 返回的 `draft.config`，不要重新组装。
- `base_version` 取 `pre_publish_checklist` 返回的 `base_version`；从未发布时是 0。
- 生产环境必须传 `confirm_project_id`。
- 先按写操作规则展示一次预览（`confirm=false`）。用户在清单阶段已经确认过配置内容，仍要把这次
  发布的目标环境、项目和配置版本说清楚再执行。
- 用户确认清单和真正发布之间隔了几轮对话时，发布前重新 `get_editor`，草稿保存时间或已发布版本
  变了就重新走清单。

返回 `conflict` 时不强行覆盖：重新 `get_editor` 读取最新的已发布版本和草稿，说明版本已被他人
更新，请用户重新确认后再发布。

发布成功后记下返回的 `version` 和 `published_at`。发布会删除草稿，之后再改配置会以这个版本为底
新建草稿。

## 全链路校验

改配置时，发布后接着调用 `verify_pipeline(env, project_id)`。新项目接入时审核员要到阶段 5 才加，
这一步放在阶段 5 之后做，不在发布后马上做。

工具只读，把 `checklist_markdown` 原样展示给用户。清单逐项打 ✅ 或 ❌：

- 有审核员：审核员数量为 0 时 ❌。
- 依赖无误：每一轮审核员 talent_id 对应的字段必须是查找引用，且引用的表在同一个多维表格里。
- 依赖无误：「人才招聘」是底表可管理协作者。
- 工作流创建：等工作流同步完成。仍在排队或执行时是 ⏳，稍后再调一次，不说成已通过。

读不到的项一律算 ❌，不要说成通过。有 ❌ 时按每项的说明处理，处理完再调一次 `verify_pipeline`：
没有审核员走 [审核员](../../audit-workbench-auditors/SKILL.md)；协作者缺失或权限不够用
`ensure_app_collaborator`；talent_id 不是引用或引用的表不在当前多维表格，请用户在飞书上改底表字段，
或在配置页换一个字段后重新发布；工作流失败走 [工作流](../../audit-workbench-workflow/SKILL.md) 的重试。
