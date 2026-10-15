# 每轮监听字段怎么猜

步骤 4 用 [scripts/guess_round_fields.py](../scripts/guess_round_fields.py)。把 `+field-list` 的完整 JSON 经 stdin 传入，`--rounds N`。

## 候选规则

排除名称含：`盲审`、`更新时间`、`建议`、`评价`、`回传`。排除类型：`button`、`formula`、`created_at`、`updated_at`。名称含 `审核员talent_id` / `审核人talent_id` 时保留 `lookup`（底表常见类型）。默认监听列就是 `审核员talent_id`。

**状态列**优先 `type=select` 且名称含 `审核状态`：

| 轮次 | 名称优先顺序 |
|---|---|
| 1 | `审核状态`，然后 `一轮审核状态` / `第1轮审核状态` / `首轮审核状态` |
| ≥2 | `二轮审核状态` / `第2轮审核状态` / `2轮审核状态`（三轮同理） |

**审核人列**默认是 `审核员talent_id`（人员列 `审核员` / `审核人` 不作为监听列）。名称必须含 `审核员talent_id`（次选 `审核人talent_id`），允许 `lookup` / `text` 等，不要求 `type=user`：

| 轮次 | 名称优先顺序 |
|---|---|
| 1 | `审核员talent_id`，然后 `审核人talent_id` / `一轮审核员talent_id` / `首轮审核员talent_id` |
| ≥2 | `二轮审核员talent_id` / `第2轮审核员talent_id` / `2轮审核员talent_id`（三轮同理） |

同表里若同时存在 `审核员`（人员）和 `审核员talent_id`，只猜后者。

脚本输出每轮 `status` / `reviewer` 的最佳猜测、`field_id`、备选列表、以及状态列上匹配到的通过选项。飞书 `+field-list` 常常不给 option id，只传 `name` 即可。

给用户时只把最佳猜测填进确认清单（列名 + `field_id`）。猜不出时该项留空，只列出名称含 `审核员talent_id` 的列名；再没有则列出名称同时含 `talent_id` 和「审核」的列名。用户改列名后，用 `+field-list` 再取 `field_id` 和 option id。
