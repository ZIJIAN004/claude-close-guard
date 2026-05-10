# claude-close-guard

> 关闭 Claude Code 终端窗口时弹一个原生窗口，汇报本次对话核心内容，让你决定写入哪些记忆。

工作机制分两层：

| 触发方式 | 拦截方式 | 能否取消关闭 | 弹窗时机 |
|---|---|---|---|
| **Alt+F4** | AHK Hotkey 同步拦截 | ✅ 能 | 关闭前 |
| **鼠标点 X / 任务栏关闭** | PowerShell `SetConsoleCtrlHandler`（需用 `ccg-claude` 启动）| ❌ 关闭无法撤销 | 关闭后立即弹窗 |

弹窗里会显示：

- 本次对话的 headline（一句话总结）
- 3-6 条 bullet 列出过程要点
- 候选记忆条目（带类型 user/feedback/project/reference），勾选要保存的项

记忆库是 markdown + sqlite-vec 双存储，并通过 MCP server 把 `search_memory` / `list_memories` 暴露给 Claude Code，让 LLM 在新对话里自动拉取相关旧记忆。

---

## 系统要求

- Windows 10 / 11
- Python ≥ 3.10
- AutoHotkey v2（用于 Alt+F4 拦截，可选但推荐）
- Claude Code CLI（可选，仅为 MCP 自动注册）
- `ANTHROPIC_API_KEY` 环境变量（总结调 Claude Haiku）

首次搜索/弹窗时会下载 `BAAI/bge-base-zh-v1.5`（约 400 MB）到 HuggingFace 缓存。

---

## 安装

```powershell
git clone https://github.com/<your-name>/claude-close-guard.git
cd claude-close-guard
.\scripts\install.ps1
```

`install.ps1` 会做：

1. 在 `~/.claude-close-guard/.venv/` 创建 venv 并 `pip install -e .`
2. 写默认配置 `~/.claude-close-guard/config.yaml` 和 `ahk.cfg`
3. 把 AHK 脚本注册成开机自启快捷方式（在 `shell:startup`），并立即启动一份
4. 把 `ccg-claude` shim 放到 `~/.claude-close-guard/bin/`，并加进用户 PATH
5. 调用 `claude mcp add ccg-memory` 把 MCP server 写进 Claude Code 用户级配置

可选参数：`-NoMcp`（跳过 MCP 注册）、`-NoStartup`（跳过 AHK 自启）。

---

## 使用

装完即用：

- **Alt+F4 关闭终端** → 弹窗，可取消可确认
- **用 `ccg-claude` 启动 Claude Code**（替代 `claude` 命令） → 鼠标点 X 关闭时仍会弹窗（事后弹），可保存记忆
- **新对话里说"上次我们决定的那个 X"** → Claude 会通过 MCP 自动调 `search_memory` 拿到对应记忆

CLI 工具：

```powershell
ccg list                  # 列出所有记忆
ccg list --type feedback  # 按类型过滤
ccg search "POMO"         # 混合检索（BM25 + 向量）
ccg show feedback_x.md    # 看完整内容
ccg reindex               # 修改 md 后重建向量索引
ccg path                  # 打印记忆库路径
```

---

## 配置

`~/.claude-close-guard/config.yaml`：

```yaml
memory_dir: ~/.claude-close-guard/memory
vector_db: ~/.claude-close-guard/vectors.sqlite

embedding_model: BAAI/bge-base-zh-v1.5
embedding_device: cpu              # cuda 也可
summarizer_model: claude-haiku-4-5-20251001
summarizer_max_tokens: 2000

target_window_classes:              # AHK Alt+F4 只对这些窗口类生效
  - CASCADIA_HOSTING_WINDOW_CLASS   # Windows Terminal
  - ConsoleWindowClass              # conhost / 旧式

mcp_top_k: 5
mcp_hybrid_alpha: 0.5               # 0=纯 BM25, 1=纯向量
min_turns_to_prompt: 3              # 短于此对话不触发总结
ui_window_size: "720x540"
```

**记忆库膨胀到 5000 条以上时**，可换成 `BAAI/bge-m3` 或 `Qwen/Qwen3-Embedding-0.6B`（只需改 `embedding_model` 后跑 `ccg reindex`）。

---

## 卸载

```powershell
.\scripts\uninstall.ps1
```

记忆库 (`~/.claude-close-guard/memory/`) 和 venv 不会被删，需要的话手动清理。

---

## 架构

```
                        Alt+F4
                          │
          ┌───────────────▼───────────────┐
          │  ahk\close_guard.ahk          │
          │  RunWait → python -m ...      │  exit 0=放行  exit 1=取消
          └───────────────┬───────────────┘
                          │
[ X / 任务栏关闭 ] ───────►│
   │                       │ python -m claude_close_guard.close_handler
   │  (ccg-claude wrapper) │   --pid <pid> [--post-close]
   │  ConsoleCtrlHandler   │
   ▼                       ▼
   spawn detached ──────►  ┌──────────────────────────┐
                           │ close_handler 主流程     │
                           │  · portalocker → master  │
                           │  · 800 ms debounce       │
                           │  · 扫 queue 收所有 PID   │
                           │  · 后台并行总结          │
                           │  · tkinter 聚合弹窗      │
                           │  · 写 done/<pid>.txt     │
                           └────────┬─────────────────┘
                                    │
                                    ▼
                           memory_store: md + sqlite-vec
                                    ▲
                                    │ search_memory
                           ┌────────┴─────────────────┐
                           │ MCP server (stdio)       │
                           └──────────────────────────┘
                                    ▲
                                    │ tool call
                           Claude Code 新对话
```

---

## 已知限制

- **鼠标点 X 无法"事前拦截"**：Windows 把 NCLBUTTONUP → SC_CLOSE → WM_CLOSE 全在目标进程内部完成，外部进程拦不住，除非做 DLL injection。本工具用"事后弹窗"代替——窗口关掉，独立弹窗进程继续问你要不要保存记忆。
- **关机/注销时**：进程被 SIGTERM 强杀，AHK / ConsoleCtrlHandler 都来不及反应。
- **Linux/macOS**：暂未支持，AHK 是 Windows-only。

---

## License

MIT
