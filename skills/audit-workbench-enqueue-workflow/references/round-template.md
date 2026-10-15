# 入队工作流步骤图

渲染脚本按这里生成 JSON。新建标题统一为 `审核工作台题目入队·第N轮`。金模板（步骤结构）在 `NFyGb7cQPaW5VjsKI51cINXknbS` 上：

- 非末轮：`入队·第1轮（review_stage=1） 副本`（`wkfAaswR0PMw3b54`）
- 末轮：`入队·第2轮（review_stage=2）`（`wkfVa0t6i5jhssLX`）

## 末轮（不串台）

```text
trig  SetRecordTrigger  监听本轮状态列 + 本轮审核员talent_id列
  └─ http  HTTPClientAction  POST enqueue review_stage=N
```

## 非末轮（晋级兜底）

```text
trig  SetRecordTrigger  监听本轮状态列 + 本轮审核员talent_id列
  └─ http  HTTPClientAction  POST enqueue review_stage=N
       └─ branch  IfElse  本轮状态 containsAny {审核通过, 审核员修改后通过}
            ├─ if_true  → http_next  POST enqueue review_stage=N+1
            └─ if_false → 结束
```

`if_false.to` 为空字符串。分支条件的 `left_value` 必须是 `$.trig.{status_field_id}`，选项带 `id` 和 `name`。

## HTTP body

三段拼接，禁止把 `record_id` 写成普通文本：

```text
{"app_token":"<app_token>","table_id":"<table_id>","review_stage":<N>,"record_id":"
 + ref $.trig.recordId +
","changed_fields":["<状态列名>", "<审核员talent_id列名>"]}
```

晋级兜底那次 HTTP 的 `review_stage` 和 `changed_fields` 用**下一轮**的列名。

URL、Header `X-API-Key`、`Content-Type: application/json` 与用户确认值一致。
