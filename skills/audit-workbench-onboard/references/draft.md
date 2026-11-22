# 阶段 2 下半：保存草稿与入队条件

## 生成并保存

`suggest_draft(env, project_id, table_url, workbench_type, alignment, limit=5)`。

工具按规则计票并组装草稿：字段过半数参考项目有对应才纳入；区域和权限取多数，打平取最近发布的
项目；布局取覆盖字段最多的参考项目；状态映射按对齐表与参考项目汇总。草稿结构与管理端保存时
一致，打开配置页就能回显。

- 项目没有草稿时直接保存并返回 `report_markdown`。
- 项目已有草稿时只返回预览，`report_markdown` 里会写明「尚未保存」。把报告给用户看，说明会
  覆盖现有草稿，得到确认后带 `confirm=true` 再调用一次；生产环境另传 `confirm_project_id`。
- 生产环境第一次调用如果是因为已有草稿而停在预览，确认时同时补 `confirm_project_id`。

把 `report_markdown` 原样展示给用户。报告分两部分：第一部分列出每轮全部推荐字段，用色块区分
展示位置、圆点区分编辑权限；第二部分只列没推荐出来和低置信的映射。结尾请用户核实三点：
字段集合是否调整、字段映射是否调整、给出每一轮的入队视图链接。

## 处理用户的修改

用户说要增减字段、改展示位置或权限时：

1. `get_editor(env, project_id)` 读取当前草稿，拿到 `draft.config` 和 `draft.updated_at`。
2. 在本地改这份 config，只改用户点名的部分，其余原样保留。
3. `save_draft` 保存，`base_updated_at` 原样回传 `draft.updated_at`，不做时区换算。默认只返回
   预览，给用户看后带 `confirm=true` 再调用一次。

不要自己重新拼一份 config，也不要用对齐表覆盖用户已经改过的内容。

## 入队视图链接

用户给出链接后调用 `set_enqueue_views(env, project_id, view_urls)`，`view_urls` 的 key 是轮次 ID
（`round-1`、`round-2`……），value 是视图链接。工具逐个解析，解析失败则不保存，把原因转述给用户。
返回里每个轮次有视图名称和筛选条件摘要，原样告诉用户，请其核对。

用户只给了一部分轮次时，只更新这些轮次，其余留空并提醒还差哪几轮。任何一轮的入队视图为空时，
不进入阶段 3：发布时会因为视图链接解析失败而被拒绝，或发布后该轮不会入队。

## 写入进度

```json
{"stage": 2, "status": "done", "draft_saved": true,
 "page_url": "https://admin-test.meetchances.com/projects/1234/audit-workbench?step=1",
 "enqueue_views": {"round-1": "...", "round-2": "..."},
 "round_count": 2, "report_shown": true}
```

如果停在等待用户提供视图链接，`status` 写 `waiting_views`，并列出缺哪几轮。
