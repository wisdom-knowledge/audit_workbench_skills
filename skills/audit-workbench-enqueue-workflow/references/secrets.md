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
3. 仍没有：停下，只发下面这句，等用户放好文件后再读。不要让用户把 Key 贴到对话里，也不要从对话写入 secrets 文件。

```text
首次使用，找 rd 同学要一份 audit-workbench-enqueue.env，添加到 ~/.agents/secrets/ 目录下。
```

展示只留末 4 位。
