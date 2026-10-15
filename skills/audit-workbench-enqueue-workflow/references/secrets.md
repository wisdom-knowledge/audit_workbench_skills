# 入队 API Key（本机 secrets 文件）

不要把 Key 写进 skill。本机文件：

`~/.agents/secrets/audit-workbench-enqueue.env`

目录权限 `700`，文件权限 `600`。格式：

```
BOE_API_KEY=...
PROD_API_KEY=...
```

读取顺序（`scripts/load_enqueue_secrets.py --env boe|prod`）：

1. 上述 secrets 文件
2. 环境变量 `AUDIT_WORKBENCH_ENQUEUE_API_KEY_BOE` / `_PROD`，再 `AUDIT_WORKBENCH_ENQUEUE_API_KEY`
3. 仍没有：向用户要 Key，确认配置时补上。用户提供后可写入 secrets 文件，不要写入 skill

展示只留末 4 位。
