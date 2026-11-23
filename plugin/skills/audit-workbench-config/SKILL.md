---
name: audit-workbench-config
description: >
  修改已接入项目的审核工作台配置并发布：增删展示字段，改字段权限、区域、布局、角色字段映射、
  审核状态映射或入队视图；放弃草稿；暂停或恢复项目。不要用于新项目接入，也不要用于只查工作流
  或审核员。
---

# 改配置

先读 [通用规则](../audit-workbench/references/rules.md)。环境和项目 ID 按入口的「定位项目」取得。

## 从哪份配置改

调用 `get_editor(env, project_id)`。

- 有草稿：在 `draft.config` 上改。草稿比已发布版本新，说明有人改了还没发布，先告诉用户草稿的
  保存时间和保存人，问是接着这份改，还是先放弃。
- 没有草稿，有已发布版本：以 `published.config` 为底改，保存时 `base_updated_at` 传 null，
  这次保存会新建草稿。
- 两者都没有：项目还没接入，转到 [接入](../audit-workbench-onboard/SKILL.md)。

## 改

1. 只改用户点名的部分，其余原样保留。不要重新拼一份 config，也不要用推荐结果覆盖用户改过的内容。
2. 要加的字段必须在底表里。用户说的字段在 `fieldCatalog` 里找不到时，先用
   `parse_feishu(env, table_url, project_id)` 刷新字段目录；仍然没有就停下，请用户确认字段名或
   先在底表加列。
3. 状态映射的目标只能是平台七个状态：待审核、审核通过、审核拒绝、已返修待审核、待返修、其他、
   做题中。模版二必须配置本轮的审核操作字段。
4. 用 `save_draft` 保存，`base_updated_at` 原样回传 `summary.draft_updated_at`，不做时区换算。
   先预览，用户同意后带 `confirm=true`。
5. 换入队视图用 `set_enqueue_views(env, project_id, view_urls)`，key 是轮次 ID（`round-1`、
   `round-2`……）。它要求已有草稿；没有草稿时先按第 4 步保存一次。返回的视图名称和筛选条件摘要
   原样告诉用户核对。

保存后给出配置页链接，用户可以在管理端看到回显。

## 发布

改完要生效就按 [发布](references/publish.md) 执行。发布后 Worker 会按新配置更新飞书工作流，
接着按 [工作流](../audit-workbench-workflow/SKILL.md) 查同步结果。列名或入队条件变了的轮次，
人工修补过的工作流不会被自动覆盖，会显示「需人工同步」。

## 其他

- 放弃草稿：`discard_draft`。草稿删除后不可恢复，已发布版本不受影响。预览时说清楚这一点。
- 暂停或恢复：`set_runtime_status`，`PAUSED` 后配置端写操作和专家端提交都不可用。预览时把
  这个影响告诉用户。
