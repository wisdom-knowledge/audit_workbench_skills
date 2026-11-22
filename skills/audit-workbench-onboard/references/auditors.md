# 阶段 5：审核员与飞书绑定

## 收集 talent_id

请用户提供审核员的 talent_id 列表。这个流程只接受 talent_id，不按姓名或手机号猜测。用户给出
姓名时，请其提供对应的 talent_id，不要自己查表匹配。

## 添加

`add_auditors(env, project_id, talent_ids)`。先预览，确认后带 `confirm=true`；生产环境另传
`confirm_project_id`。

返回里 `added`、`skipped` 都要向用户说明：已在名单中的会被跳过，不存在的 talent_id 会在
`skipped` 里给出原因。一个都没加上时停下来，请用户核对 talent_id，不要继续后面的绑定检查。

## 检查飞书绑定

`check_auditor_binding(env, project_id, talent_ids)`。把 `binding_markdown` 原样展示给用户。

结果分三类：

- `BOUND` 已绑定，列出飞书账号名。
- `UNBOUND` 未绑定，输出里用 🔴 标出。必须明确提醒用户：**通知这些审核员在专家端自行完成
  飞书账号绑定**。这是用户要做的动作，不要替他发消息，也不要说成已经绑定。
- `UNVERIFIED` 读绑定表失败，无法判断是否绑定。单独说明并建议稍后重试，不要当成未绑定，
  否则会让已绑定的审核员被误催。

绑定表里没有记录的人，工具不会替他绑定；这一步只负责查出来并提醒。

## 写入进度

```json
{"stage": 5, "status": "done", "auditors_added": [101, 102],
 "unbound": [102], "unverified": []}
```

`unbound` 非空时，在阶段 6 的交付里列为仍需人工处理的事项。
