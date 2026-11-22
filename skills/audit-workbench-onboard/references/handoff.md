# 阶段 4：工作流交接

## 等待同步并列出工作流

发布成功后调用 `created_workflows(env, project_id, timeout=90)`。工具内部会等同步完成，再用
lark-cli 回读每条工作流在飞书上的启用状态和人工修补状态。

把 `workflows_markdown` 原样展示给用户。它列出每条工作流的同步状态、是否已启用、是否已修补
和链接，末尾请用户确认后启用。

- `timed_out=true` 时告诉用户还有工作流在同步，稍后再查一次，不要询问是否启用。可以再次调用
  `created_workflows`，或只查状态用 `get_workflows`。
- 有 `problems` 时逐条转述。同步失败或状态为 `failed` 的，先用 `retry_workflows` 只重试出错的
  那几个轮次和种类：先展示预览，确认后带 `confirm=true` 执行，再重新调用 `created_workflows`。
  重试不会无限进行：Worker 每条最多尝试 5 次，失败后按 3n 秒退避；手动重试会清零计数。
- 状态为 `manual` 时说明配置有变化但工作流已人工修补，未被自动更新，按返回的说明请用户在
  飞书上按新列名修改，或用 `forceUpdate` 重试覆盖（会丢失人工补的步骤）。

## 模版二的人工修补

清单里 `repaired=false` 的「审核操作」工作流必须先修补。给用户具体动作：打开该工作流链接，
在触发后的第一步加一个「修改记录」，把本轮审核操作列设为空。原因是接口建不出清空单选这一步，
不补的话审核员点过一次后这一列不会清空，下一次操作触发不了。

用户说补完后，再调用一次 `created_workflows` 回读。只有工具确认 `repaired=true` 才能进入启用。
不要凭用户说「补好了」就跳过回读。

## 启用

用户确认清单无误后调用 `enable_workflows(env, project_id)`，先预览；确认后带 `confirm=true`，
生产环境另传 `confirm_project_id`。工具只启用已同步、且在飞书上确实处于未启用的工作流；
未修补的模版二审核操作工作流会被跳过，并在结果里说明原因。

启用后工具会回读状态。返回里 `ok=false` 的条目逐条转述原因，不要重复调用同一条超过一次。

## 写入进度

```json
{"stage": 4, "status": "done", "workflows_enabled": ["一轮 · 入队", "二轮 · 入队"],
 "template2_repair_confirmed": true, "pending": []}
```

还在等人工修补时写 `status: waiting_repair`，并记下缺哪几条。
