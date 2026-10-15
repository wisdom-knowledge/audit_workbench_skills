# 安装

规范位置是 `~/.agents/skills/audit-workbench-enqueue-workflow`。其它 agent 的 skill 目录只放指向这里的符号链接。

```bash
python3 scripts/install.py
python3 scripts/install.py --dry-run
```

脚本会：

1. 把本 skill 安装到 `~/.agents/skills/<name>`（已在该处则跳过拷贝）
2. 扫描本机用户级 skill 目录并建立同名 symlink

会处理的目录（父目录已存在才会创建 `skills/`）：

- `~/.agents/skills`
- `~/.codex/skills`（若已整体链到 `.agents/skills` 则跳过）
- `~/.claude/skills`
- `~/.cursor/skills` / `~/.gemini/skills` / `~/.grok/skills` / `~/.opencode/skills`
- `~/.trae-cn/builtin/global/skills`
- `$CODEX_HOME/skills`
- 其它 `~/.*/skills`（排除 plugins / marketplace / cache / extensions）

不链到各产品的插件缓存目录。安装后当前会话未必立刻可见，下一轮对话再调用。
