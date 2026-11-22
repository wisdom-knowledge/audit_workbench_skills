# 续接规则

用户说「继续」「接着做」，或在新会话里恢复这个项目的接入时，先读这一份。

## 进度文件

路径固定为当前工作区的 `.audit-workbench-onboard/progress.json`。目录不存在时创建。内容是一个
JSON 对象，随每个阶段更新一次：

```json
{"stage": 3, "status": "done", "env": "boe", "project_id": 1234,
 "table_url": "...", "app_token": "...", "table_id": "...", "workbench_type": 1,
 "published_version": 1, "updated_at": "2026-11-22T10:00:00Z"}
```

各阶段的参考文件里都给了该阶段要补的字段。至少保留 `stage`、`status`、`env`、`project_id`、
`updated_at`。`status` 取 `done`、`waiting_views`、`waiting_repair`、`blocked` 之一。

用 `scripts/progress.py` 读写，不要手写 JSON：

```bash
python3 scripts/progress.py show
python3 scripts/progress.py update --stage 3 --status done --env boe --project-id 1234 --field published_version=1
```

`update` 会合并字段而不是覆盖整份文件。`--field` 可重复，值按 JSON 解析；字符串直接写文本，
整数、布尔、数组写成 JSON 字面量。不传 `--stage` 时只合并字段。

## 恢复前先回读线上

读进度后，按当前阶段调用一次工具核对线上状态，不能只信进度文件：

| 当前阶段 | 回读 |
|-|-|
| 1 | `get_editor` |
| 2 | `get_editor`（看草稿是否还在、`draft_updated_at` 是否变化） |
| 3 | `check_readiness` 与 `pre_publish_checklist` |
| 4 | `created_workflows` 或 `get_workflows` |
| 5 | `check_auditor_binding` |
| 6 | `get_editor` 与 `get_workflows` |

不一致时以线上为准，并用一句话说明差异。常见情况：

- 进度写「已有草稿」，线上草稿没了或被别人改了：重新走阶段 2，不要拿旧 config 保存。
- 进度写的版本和线上 `published_version` 不同：说明配置已被他人发布，重新确认后再继续。
- 工作流状态与进度不同：以 `get_workflows` 的结果为准。
- 用户登录态失效：返回 `unauthorized` 时调用 `login`，再重试一次刚才的回读。

进度里 `status=waiting_views` 时，从「等用户提供入队视图链接」处接着走；`waiting_repair` 时
从「回读模版二修补状态」处接着走；`blocked` 时先说明当时卡住的原因，再让用户决定是否重试。

## 不要做的事

不从进度文件恢复写操作，不因为进度写 `done` 就跳过用户确认，不用旧进度里的 config 直接发布。
