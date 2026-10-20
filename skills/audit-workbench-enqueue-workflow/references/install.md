# 安装

使用者本机只装入口。之后每次用这个 skill，入口会从 GitHub `main` 拉最新正文到 `~/.agents/cache/audit_workbench_skills`，再按那份执行。

```bash
python3 scripts/install.py
python3 scripts/install.py --dry-run
```

脚本会：

1. 把 `bootstrap/SKILL.md` 和 `scripts/sync_from_github.py` 装到 `~/.agents/skills/<name>`
2. 扫描本机用户级 skill 目录并建立同名 symlink

已装过旧版（整份拷贝）的人再跑一次 `install.py` 换成入口。之后不必 `git pull`。

开发者把规范目录链到本仓库（不拉远程）：

```bash
python3 scripts/install.py --local
```

会处理的目录（父目录已存在才会创建 `skills/`）：

- `~/.agents/skills`
- `~/.codex/skills`（若已整体链到 `.agents/skills` 则跳过）
- `~/.claude/skills`
- `~/.cursor/skills` / `~/.gemini/skills` / `~/.grok/skills` / `~/.opencode/skills`
- `~/.trae-cn/builtin/global/skills`
- `$CODEX_HOME/skills`
- 其它 `~/.*/skills`（排除 plugins / marketplace / cache / extensions）

不链到各产品的插件缓存目录。安装后当前会话未必立刻可见，下一轮对话再调用。私有仓库需要本机已有 GitHub SSH 或 HTTPS 权限。
