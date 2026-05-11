# claude-close-guard

> 解决 Claude Code 两个老问题：① 手一抖关窗一晚上对话没了；② auto-memory 什么都塞，记忆库越用越乱。在关闭终端的那一刻强制弹窗，AI 提议 + 人工勾选，写入 markdown + 向量库，新会话通过 MCP 自动召回。

适用于 Windows + PowerShell / Windows Terminal 下使用 Claude Code 的人。装好后不需要在结束对话前手动复制粘贴重要结论——关窗时自然会问你。

---

## 它解决什么

**痛点 1 — 误关失救**
手抖按 Alt+F4，或者点错右上角 ×，一晚上敲定的方案、踩过的坑、决定的下一步全消失。Claude Code 关掉就是真的关掉了。

**痛点 2 — 记忆库膨胀**
Claude Code 内置的 auto-memory（以及其他全自动记忆工具）会把代码片段、git history、一次性 debug、临时任务状态都往里写。两周后翻不动，三周后没人愿意再看，最终变成杂物间。

**本工具做了什么**

- **关窗瞬间强制总结**：Alt+F4 → 阻塞弹窗可撤销；鼠标点 × → 终端关掉后立即独立弹窗（用 `ccg-claude` 启动才有此层）
- **AI 提议 + 人工勾选两道关**：summarizer 在 system prompt 里**显式拒绝**写入「代码模式 / git history / 一次性修复 / 临时状态」这些会膨胀但不值得记的类型；再由你二次过滤勾选
- **多窗口同时关** → 自动聚合成单个弹窗（左右切换），不会爆 N 个对话框
- **持久化** → markdown（真相源）+ sqlite-vec（向量索引副本）
- **MCP 自动召回** → `search_memory` / `list_memories` 工具注入 Claude Code，新对话里 LLM 自己调
- **零额外凭证** → 默认 `claude -p` 复用 Claude Code 现有 OAuth，不需要 API key

弹窗界面是暗色等宽风（Cascadia Mono + Claude orange），与 PowerShell 窗体观感统一。

---

## 界面预览

```
╔═══════════════════════════════════════════════════════════════════════╗
║  claude-close-guard  ·  save memories                       ◀ 1 / 2 ▶ ║
╟───────────────────────────────────────────────────────────────────────╢
║                                                                       ║
║  ❯  PID 12345  ·  POMO-Entropy                                        ║
║                                                                       ║
║  POMO PRM gap analysis + minimum verification plan                    ║   ← headline (Claude orange)
║                                                                       ║
║  ─  Confirmed depot signal gap and weak-early/strong-late curve       ║
║  ─  Decision: do not strip depot, feed it as a normal node            ║
║  ─  Next: small-model GRPO+POMO vs SFT+GRPO comparison                ║
║  ─  Deadline: 2026-04-30 — RL + latent-reasoning milestone            ║
║                                                                       ║
║  ───────────────────────────────────────────────────────────────────  ║
║  memory candidates                                                    ║
║                                                                       ║
║  ┌─────────────────────────────────────────────────────────────────┐  ║
║  │ [x]  project   pomo-prm-known-gaps                              │  ║
║  │      POMO PRM has two known gaps to revisit after first run    │  ║
║  │      depot signal missing + early curve weak, late curve …     │  ║
║  └─────────────────────────────────────────────────────────────────┘  ║
║                                                                       ║
║  ┌─────────────────────────────────────────────────────────────────┐  ║
║  │ [x]  feedback  tsp-depot-as-node                                │  ║
║  │      TSP eval feeds depot as a normal node into POMO            │  ║
║  │      Why: model must perceive starting point …                  │  ║
║  └─────────────────────────────────────────────────────────────────┘  ║
║                                                                       ║
╟───────────────────────────────────────────────────────────────────────╢
║  esc to cancel  ·  enter to confirm       [ cancel close ][ save & close ]
╚═══════════════════════════════════════════════════════════════════════╝
```

颜色映射：headline = Claude orange `#d97757`；`[project]` 绿 `#a3be8c`、`[feedback]` 橙 `#d97757`、`[user]` 蓝 `#5fafef`、`[reference]` 紫 `#b48ead`；底色 `#1e1e1e`，候选卡片 `#252526`。

多窗口同时关闭时顶部右上出现 `◀ 1/2 ▶` 切换器，只有一个会话时隐藏。

---

## 快速开始

```powershell
git clone https://github.com/ZIJIAN004/claude-close-guard.git
cd claude-close-guard
.\scripts\install.ps1
```

打开新的 PowerShell，用 `ccg-claude` 启动 Claude Code（替代 `claude`）：

```powershell
ccg-claude
```

聊几轮，然后随便用什么方式关终端（Alt+F4 / ×）。弹窗里勾上你想留的记忆条目，点 `save & close`。

---

## 系统要求

| 必需 | 用途 |
|---|---|
| Windows 10 / 11 | AHK + ConsoleCtrlHandler 是 Windows-only |
| Python ≥ 3.10 | 主运行时 |
| Claude Code CLI（已登录 OAuth） | 总结调用 `claude -p`，MCP 自动注册 |

| 可选 | 用途 |
|---|---|
| AutoHotkey v2 | Alt+F4 同步拦截（缺它只剩"事后弹窗"层） |
| `ANTHROPIC_API_KEY` | 没安装 Claude Code CLI 时的总结回退路径 |
| CUDA GPU | 想加速 embedding，可把 `embedding_device` 改成 `cuda` |

首次运行 `ccg search` 或 MCP server 时会下载 `BAAI/bge-base-zh-v1.5`（约 400 MB）到 HuggingFace 缓存目录。

---

## 安装

### 自动安装（推荐）

```powershell
.\scripts\install.ps1
```

`install.ps1` 做的事：

1. 在 `~/.claude-close-guard/.venv/` 建 venv，先装 CPU-only torch（避免装到 2.5 GB CUDA 版），然后 `pip install -e .`
2. 写默认 `config.yaml` 和 `ahk.cfg`（不带 BOM，AHK 才认）
3. 把 `ccg.cmd` / `ccg-mcp.cmd` / `ccg-claude.cmd` shim 拷到 `~/.claude-close-guard/bin/`，并把这个 bin 目录加进用户 PATH
4. 调 `claude mcp add ccg-memory --scope user` 把 MCP server 注册到 Claude Code 用户级配置
5. 找到 AutoHotkey v2 可执行文件（搜索 `Program Files` 与 `LOCALAPPDATA` 两处），在启动文件夹放一个快捷方式开机自启 AHK 脚本，并立即起一份

可选参数：

- `-NoMcp` 跳过 MCP 注册
- `-NoStartup` 跳过 AHK 自启快捷方式

### 仅手动验证

```powershell
ccg path                     # 应输出记忆目录
ccg list                     # 列出已有记忆（首次为空）
claude mcp list              # 应能看到 ccg-memory
```

---

## 使用

### 三种使用流

**1) Alt+F4 流（同步阻塞）**

任何在 Windows Terminal / conhost 里运行的 Claude Code 都受 AHK 守护。按 Alt+F4 后弹窗会**阻塞 Alt+F4**——你可以取消、也可以确认。需要 AutoHotkey v2 已装且 `install.ps1` 跑过。

**2) 鼠标点 × 流（事后弹窗）**

Windows 不允许外部进程拦截 × 按钮（系统限制，除非 DLL 注入）。所以这一层走另一种方案：

```powershell
ccg-claude        # 替代直接 `claude` 命令
```

`ccg-claude` 是个 PowerShell 包装器，它在子进程里注册 `SetConsoleCtrlHandler`。当 Windows 发 `CTRL_CLOSE_EVENT` 时，handler 在主进程被回收前 fork 一个独立 pythonw 进程，用 `UseShellExecute=true` 启动——所以终端死了，弹窗活着。

**3) MCP 检索流（新会话里）**

新开 Claude Code 对话，说"我之前怎么处理 X 的"或者"上次我们决定的那个方案"。LLM 看到 `search_memory` 工具会主动调用，返回最相关的 markdown 内容。

也可以手动用 CLI 验证：

```powershell
ccg search "POMO"
ccg search "深度学习训练 GPU 配置" --top-k 10
```

### CLI 命令

```powershell
ccg list                    # 列出全部记忆
ccg list --type feedback    # 按类型过滤（user/feedback/project/reference）
ccg search "<query>"        # BM25 + 向量混合检索
ccg show feedback_xxx.md    # 看某条完整内容
ccg reindex                 # 手动改了 md 后重建向量索引
ccg path                    # 打印记忆目录路径
```

### MCP 工具（Claude Code 自动调）

| 工具 | 参数 | 作用 |
|---|---|---|
| `search_memory` | `query: string, top_k: int = 5` | 混合检索，返回 markdown 片段 |
| `list_memories` | `type_filter: string \| None` | 按类型列举 |

---

## 配置

`~/.claude-close-guard/config.yaml`：

```yaml
memory_dir: ~/.claude-close-guard/memory
vector_db: ~/.claude-close-guard/vectors.sqlite

embedding_model: BAAI/bge-base-zh-v1.5
embedding_device: cpu                    # cuda 可加速
summarizer_model: claude-haiku-4-5-20251001
summarizer_max_tokens: 2000

target_window_classes:                   # AHK Alt+F4 只对这些窗口类生效
  - CASCADIA_HOSTING_WINDOW_CLASS        # Windows Terminal
  - ConsoleWindowClass                   # conhost / 旧式

mcp_top_k: 5
mcp_hybrid_alpha: 0.5                    # 0=纯 BM25, 1=纯向量
min_turns_to_prompt: 3                   # 短于此轮数不触发总结
ui_window_size: "780x600"
```

**记忆库膨胀到 5000 条以上**：换成 `BAAI/bge-m3` 或 `Qwen/Qwen3-Embedding-0.6B`，改 `embedding_model` 后跑 `ccg reindex`。

**想换总结模型**：改 `summarizer_model`。这个值通过 `--model` 传给 `claude -p`。

---

## 记忆格式

每条记忆是一个 markdown 文件，YAML frontmatter 描述元信息：

```markdown
---
name: tsp-depot-as-node
description: TSP eval 时 depot 作为普通节点喂入 POMO，不剥离
type: feedback
---

TSP 评估时 depot 直接作为普通节点喂入 POMO，不剥离

**Why:** 保证模型感知出发点
**How to apply:** 任何 TSP / VRP eval pipeline 不要预处理 depot
```

四种类型：

| type | 用途 |
|---|---|
| `user` | 用户角色、知识背景、偏好 |
| `feedback` | 用户给的工作方式指导（修正 or 验证过的方法） |
| `project` | 正在做的事、决策、deadline、动机 |
| `reference` | 外部系统的指针（Linear 项目、Grafana 看板） |

`INDEX.md` 由 `update_index()` 自动生成，按 type 分节。

---

## 工作原理

```
                        Alt+F4
                          │
          ┌───────────────▼───────────────┐
          │  ahk\close_guard.ahk          │
          │  RunWait → python -m ...      │  exit 0 = 放行 / 1 = 取消
          └───────────────┬───────────────┘
                          │
[ 鼠标点 × / 任务栏关闭 ]─►│
   │                       │ python -m claude_close_guard.close_handler
   │  (ccg-claude wrapper) │   --pid <pid> [--post-close]
   │  ConsoleCtrlHandler   │
   ▼                       ▼
   spawn detached ──────►  ┌──────────────────────────┐
                           │ close_handler            │
                           │  · portalocker 抢 master │
                           │  · 800 ms debounce       │
                           │  · 扫 queue/ 收所有 PID  │
                           │  · 并发后台总结          │
                           │  · tkinter 聚合弹窗      │
                           │  · 写 done/<pid>.txt     │
                           └────────┬─────────────────┘
                                    │
                                    ▼
                           memory_store: md + sqlite-vec
                                    ▲
                                    │ search_memory / list_memories
                           ┌────────┴─────────────────┐
                           │ MCP server (stdio)       │
                           └──────────────────────────┘
                                    ▲
                                    │ tool call
                           Claude Code 新对话
```

**多窗口同时关 → 单弹窗** 的实现：每个被关闭的窗口都把自己 PID 写进 `state/queue/<pid>.json`，然后竞争 `master.lock`（portalocker），抢到的进程睡 800 ms 收齐所有同批关闭，渲染单个聚合 UI；其它进程作为 worker 轮询 `state/done/<pid>.txt` 等待结果。

---

## 故障排查

| 症状 | 原因 + 处理 |
|---|---|
| Alt+F4 没弹窗 | `tasklist /fi "imagename eq AutoHotkey64.exe"` 看 AHK 在不在；不在就手动启动 `ahk\close_guard.ahk` 或检查 `~/.claude-close-guard/ahk.log` |
| 鼠标点 × 不弹窗 | 确认你是用 `ccg-claude` 启动的，不是 `claude`；只有 wrapper 注册了 ConsoleCtrlHandler |
| `ccg-claude` 报"cannot locate python" | 多半是 `ahk.cfg` 带了 UTF-8 BOM。重跑 `install.ps1` 或用 `[System.IO.File]::WriteAllText` 重写该文件 |
| 总结很慢（30s+） | `config.yaml` 的 `summarizer_model` 改成 haiku，或检查 `~/.claude-close-guard/close-guard.log` 看哪一步慢 |
| `TypeError: Could not resolve authentication method` | Claude Code CLI 没登录。运行一次 `claude` 走完 `/login`，或设 `ANTHROPIC_API_KEY` 走 SDK 回退 |
| `ccg-mcp` 在 Claude Code 里卡住 | pip 的 console_scripts launcher 在 Windows 多进程下会死锁。`install.ps1` 已经用 `.cmd` shim 绕过；如果你手动注册过 MCP，删了重跑 `install.ps1` |
| 中文搜索质量差 | 检查 `embedding_model` 是不是 zh 模型；非中文项目可换成 `BAAI/bge-m3` 通吃多语 |

日志：`~/.claude-close-guard/close-guard.log`（close_handler 主流程）+ `~/.claude-close-guard/ahk.log`（AHK 调用记录）。

---

## 已知限制

- **鼠标点 × 无法事前拦截**：Windows 把 `NCLBUTTONUP` → `SC_CLOSE` → `WM_CLOSE` 全在目标进程内完成，外部进程没机会插入；除非做 DLL injection（不在本项目范围）。用"事后弹窗"代替——窗口死了，弹窗进程独立活着。
- **关机 / 注销时**：进程被 `SIGTERM` 强杀，AHK / ConsoleCtrlHandler 都来不及反应。
- **Linux / macOS**：暂不支持。AHK 是 Windows-only；Linux 上窗口管理器各异需要单独适配。
- **MCP server 冷启动 ~3 秒**：sentence-transformers 加载 BGE 模型有开销，首次 `search_memory` 会感觉慢。

---

## 卸载

```powershell
.\scripts\uninstall.ps1
```

会清掉 venv、PATH、AHK 自启快捷方式、MCP 注册。**记忆库 `~/.claude-close-guard/memory/` 和 vector DB 保留**，需要的话手动删。

---

## 隐私

- 总结调用走你本机的 `claude` CLI（OAuth）或 `ANTHROPIC_API_KEY`，对话内容会发到 Anthropic API
- embedding 完全本地，不出网（除了首次下载模型）
- 没有任何遥测；本项目不联网除非你显式调 `ccg search`

---

## License

MIT — see [LICENSE](LICENSE).
