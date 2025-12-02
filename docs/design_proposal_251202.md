# 设计提案：Web 服务 CLI 流式输出

**日期**: 2025-12-02
**状态**: 待实现

---

## 一、背景与目标

### 1.1 背景

当前 CLI 诊断工具（`python -m dbdiag cli`）仅支持本地终端访问。用户希望：
- 从其他机器通过浏览器访问诊断服务
- 实时流式输出 CLI 内容
- 安全性：只允许 dbdiag 操作，不能执行任意 shell 命令
- 支持多用户并发访问互不影响

### 1.2 目标

| 目标 | 说明 |
|------|------|
| **远程访问** | 通过浏览器从任意机器访问 |
| **实时流式** | 基于 WebSocket 的输出流式传输 |
| **安全隔离** | API 级别隔离，不暴露 shell |
| **多用户** | 连接级别的会话隔离 |
| **代码复用** | 与现有 CLI 共享渲染逻辑 |

### 1.3 决策点

| 决策点 | 选择 |
|--------|------|
| 前端风格 | 仿 CLI（Rich HTML 导出） |
| 认证方式 | 无认证（内网使用） |
| 诊断模式 | 默认 Hyb（config.yaml 可配置） |

---

## 二、架构概览

### 2.1 系统架构

```
+-----------------------------------------------------------------------+
|                          System Architecture                           |
+-----------------------------------------------------------------------+
|                                                                       |
|  +-------------------+          WebSocket          +----------------+ |
|  |      Browser      | <=========================> |    FastAPI     | |
|  |  (HTML + JS/CSS)  |         JSON + HTML         |    Backend     | |
|  +-------------------+                             +-------+--------+ |
|                                                            |          |
|                                                            v          |
|                                              +-------------+--------+ |
|                                              |  GARDialogueManager  | |
|                                              |   (hybrid_mode=True) | |
|                                              +-------------+--------+ |
|                                                            |          |
|                                                            v          |
|                                              +-------------+--------+ |
|                                              |   SQLite Database    | |
|                                              |    (tickets.db)      | |
|                                              +----------------------+ |
|                                                                       |
+-----------------------------------------------------------------------+
```

### 2.2 请求流程

```
+-----------------------------------------------------------------------+
|                            Request Flow                                |
+-----------------------------------------------------------------------+
|                                                                       |
|  Browser                    Backend                   DialogueManager |
|     |                          |                            |         |
|     |  1. Connect WebSocket    |                            |         |
|     | -----------------------> |                            |         |
|     |                          |  2. Create Session         |         |
|     |                          | -------------------------> |         |
|     |                          |                            |         |
|     |  3. Send Message         |                            |         |
|     |  {"type": "message",     |                            |         |
|     |   "content": "..."}      |                            |         |
|     | -----------------------> |                            |         |
|     |                          |  4. Process Message        |         |
|     |                          | -------------------------> |         |
|     |                          |                            |         |
|     |                          |  5. Return Response        |         |
|     |                          | <------------------------- |         |
|     |                          |                            |         |
|     |  6. Send HTML Output     |                            |         |
|     |  {"type": "output",      |                            |         |
|     |   "html": "..."}         |                            |         |
|     | <----------------------- |                            |         |
|     |                          |                            |         |
+-----------------------------------------------------------------------+
```

### 2.3 安全模型

```
+-----------------------------------------------------------------------+
|                           Security Model                               |
+-----------------------------------------------------------------------+
|                                                                       |
|  What Users CAN Do:                What Users CANNOT Do:              |
|  +---------------------------+     +-----------------------------+    |
|  | - Send diagnostic message |     | - Execute shell commands    |    |
|  | - Send feedback (confirm/ |     | - Access filesystem         |    |
|  |   deny phenomena)         |     | - Run arbitrary code        |    |
|  | - Use commands: /help,    |     | - Access other users'       |    |
|  |   /reset, /exit           |     |   sessions                  |    |
|  +---------------------------+     +-----------------------------+    |
|                                                                       |
|  Implementation:                                                      |
|  - Backend exposes ONLY DialogueManager API                           |
|  - No shell/pty spawning                                              |
|  - Each WebSocket connection has isolated session                     |
|                                                                       |
+-----------------------------------------------------------------------+
```

---

## 三、详细设计

### 3.1 文件结构

```
dbdiag/
├── api/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口（已有）
│   └── websocket.py         # 新增：WebSocket 聊天端点
├── cli/
│   ├── __init__.py
│   ├── main.py              # 现有 CLI
│   └── rendering.py         # 新增：共享渲染逻辑（抽取）
├── web/
│   └── static/
│       ├── index.html       # 新增：Web 页面
│       └── style.css        # 新增：CLI 风格样式
└── ...
```

### 3.2 后端设计

#### 3.2.1 WebSocket 会话处理器

```python
# dbdiag/api/websocket.py

from fastapi import WebSocket, WebSocketDisconnect
from rich.console import Console

class WebChatSession:
    """每个连接的独立聊天会话"""

    def __init__(self, websocket: WebSocket, config: dict):
        self.websocket = websocket
        self.console = Console(record=True, force_terminal=True)
        self.dialogue_manager = GARDialogueManager(
            db_path, llm_service, embedding_service,
            hybrid_mode=config.get("diagnosis_mode") == "hyb",
            progress_callback=self._on_progress,
        )
        self.session_id = None

    async def handle_message(self, msg: dict):
        """处理传入消息"""
        msg_type = msg.get("type")
        content = msg.get("content", "")

        if msg_type == "message":
            return await self._process_diagnosis(content)
        elif msg_type == "command":
            return await self._process_command(content)

    async def _process_diagnosis(self, content: str):
        """处理诊断消息"""
        if not self.session_id:
            response = self.dialogue_manager.start_conversation(content)
            self.session_id = response.get("session_id")
        else:
            response = self.dialogue_manager.continue_conversation(
                self.session_id, content
            )

        # 使用 Rich 渲染为 HTML
        html = self._render_response(response)
        return {"type": "output", "html": html}

    async def _process_command(self, command: str):
        """处理 CLI 命令"""
        if command == "/help":
            return {"type": "output", "html": self._render_help()}
        elif command == "/reset":
            self.session_id = None
            return {"type": "output", "html": "<p>会话已重置。</p>"}
        elif command == "/exit":
            return {"type": "close"}
        else:
            return {"type": "output", "html": f"<p>未知命令: {command}</p>"}
```

#### 3.2.2 WebSocket 端点

```python
# dbdiag/api/websocket.py

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    session = WebChatSession(websocket, config)

    # 发送欢迎消息
    await websocket.send_json({
        "type": "output",
        "html": session.render_welcome()
    })

    try:
        while True:
            msg = await websocket.receive_json()
            response = await session.handle_message(msg)

            if response.get("type") == "close":
                break

            await websocket.send_json(response)

    except WebSocketDisconnect:
        pass  # 客户端断开
    finally:
        # 清理会话资源
        session.cleanup()
```

### 3.3 渲染逻辑抽取

从 `cli/main.py` 抽取共享渲染逻辑：

```python
# dbdiag/cli/rendering.py

from rich.console import Console, Group
from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown

class DiagnosisRenderer:
    """CLI 和 Web 共享的渲染逻辑"""

    def __init__(self, console: Console = None):
        self.console = console or Console()

    def render_welcome(self, mode: str = "hyb") -> Group:
        """渲染欢迎消息"""
        logo = self._get_logo(mode)
        return Group(
            Text(logo, style="bold blue"),
            Text(f"诊断模式: {mode.upper()}", style="bold"),
        )

    def render_status_bar(self, stats: dict) -> Group:
        """渲染状态栏（含统计和假设置信度条）"""
        # 轮次 | 推荐 | 确认 | 否认
        stats_text = Text()
        stats_text.append("轮次 ", style="dim")
        stats_text.append(str(stats.get("round", 0)), style="bold")
        stats_text.append("  │  ", style="dim")
        stats_text.append("推荐 ", style="dim")
        stats_text.append(str(stats.get("recommended", 0)), style="bold")
        stats_text.append("  │  ", style="dim")
        stats_text.append("确认 ", style="dim")
        stats_text.append(str(stats.get("confirmed", 0)), style="bold green")
        stats_text.append("  │  ", style="dim")
        stats_text.append("否认 ", style="dim")
        stats_text.append(str(stats.get("denied", 0)), style="bold red")

        parts = [stats_text]

        # 假设置信度条
        for i, (conf, desc) in enumerate(stats.get("hypotheses", [])[:3], 1):
            bar = self._render_confidence_bar(i, conf, desc)
            parts.append(bar)

        return Group(*parts)

    def render_recommendation(self, phenomena: list) -> Group:
        """渲染现象推荐"""
        parts = [Text(f"建议确认以下 {len(phenomena)} 个现象：",
                      style="bold yellow")]

        for i, item in enumerate(phenomena, 1):
            parts.extend(self._render_phenomenon(i, item))

        parts.append(Text("请输入检查结果（如：1确认 2否定）", style="bold yellow"))
        return Group(*parts)

    def render_diagnosis(self, response: dict) -> Panel:
        """渲染诊断结果"""
        root_cause = response.get("root_cause", "未知")
        summary = response.get("diagnosis_summary", "")
        citations = response.get("citations", [])

        content_parts = [
            Text(f"根因: {root_cause}\n", style="green bold"),
        ]

        if summary:
            content_parts.append(Markdown(summary))

        if citations:
            content_parts.append(Text("\n引用工单:", style="bold"))
            for c in citations:
                content_parts.append(
                    Text(f"  [{c['ticket_id']}] {c['description']}")
                )

        return Panel(
            Group(*content_parts),
            title="✓ 根因已定位",
            border_style="green",
        )

    def _render_confidence_bar(self, idx: int, conf: float, desc: str) -> Text:
        """渲染置信度条"""
        filled = int(conf * 10)
        empty = 10 - filled

        line = Text()
        line.append(f"{idx}. ", style="dim")
        line.append("█" * filled, style="green")
        line.append("░" * empty, style="dim")
        line.append(f" {conf:.0%} ", style="bold")
        line.append(desc[:35] + "..." if len(desc) > 35 else desc)
        return line

    def _render_phenomenon(self, idx: int, item: dict) -> list:
        """渲染单个现象"""
        p = item.get("phenomenon")
        reason = item.get("reason", "")

        parts = [
            Text(f"\n[{idx}] {p.phenomenon_id}", style="bold yellow"),
            Text(f"    {p.description}"),
        ]

        if p.observation_method:
            parts.append(Text("    观察方法:", style="dim"))
            parts.append(Text(f"    {p.observation_method}"))

        if reason:
            parts.append(Text(f"    推荐原因: {reason}", style="italic dim"))

        return parts
```

### 3.4 CLI 重构

更新现有 CLI 使用共享渲染器：

```python
# dbdiag/cli/main.py

from dbdiag.cli.rendering import DiagnosisRenderer

class GARCLI(CLI):
    def __init__(self):
        super().__init__()
        self.renderer = DiagnosisRenderer(self.console)
        # ... 其余初始化

    def _render_footer(self) -> Group:
        """使用共享渲染器"""
        return self.renderer.render_status_bar(self.stats)

    def _render_phenomenon_recommendation(self, response: dict):
        """使用共享渲染器"""
        phenomena = response.get("phenomena_with_reasons", [])
        content = self.renderer.render_recommendation(phenomena)
        self._print_indented(content)
```

### 3.5 前端设计

#### 3.5.1 HTML 结构

```html
<!-- dbdiag/web/static/index.html -->
<!DOCTYPE html>
<html>
<head>
    <title>DBDIAG Web Console</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div id="terminal">
        <div id="output"></div>
        <div id="input-line">
            <span class="prompt">&gt; </span>
            <input type="text" id="input" autofocus
                   placeholder="输入问题描述开始诊断...">
        </div>
    </div>

    <script>
        const ws = new WebSocket(`ws://${location.host}/ws/chat`);
        const output = document.getElementById('output');
        const input = document.getElementById('input');

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'output') {
                output.innerHTML += msg.html;
                output.scrollTop = output.scrollHeight;
            } else if (msg.type === 'close') {
                ws.close();
            }
        };

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && input.value.trim()) {
                const content = input.value.trim();

                // 回显输入
                output.innerHTML += `<div class="user-input">&gt; ${content}</div>`;

                // 发送消息
                if (content.startsWith('/')) {
                    ws.send(JSON.stringify({type: 'command', content}));
                } else {
                    ws.send(JSON.stringify({type: 'message', content}));
                }

                input.value = '';
            }
        });
    </script>
</body>
</html>
```

#### 3.5.2 CSS 样式

```css
/* dbdiag/web/static/style.css */

body {
    margin: 0;
    padding: 0;
    background: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 14px;
}

#terminal {
    max-width: 900px;
    margin: 20px auto;
    padding: 20px;
}

#output {
    white-space: pre-wrap;
    line-height: 1.4;
}

#input-line {
    display: flex;
    margin-top: 10px;
}

.prompt {
    color: #569cd6;
    font-weight: bold;
}

#input {
    flex: 1;
    background: transparent;
    border: none;
    color: #d4d4d4;
    font-family: inherit;
    font-size: inherit;
    outline: none;
}

.user-input {
    color: #569cd6;
    margin: 10px 0;
}

/* Rich HTML 导出的样式 */
.rich-text { }
.bold { font-weight: bold; }
.dim { opacity: 0.7; }
.green { color: #6a9955; }
.red { color: #f14c4c; }
.yellow { color: #dcdcaa; }
.cyan { color: #4ec9b0; }
.blue { color: #569cd6; }
```

---

## 四、配置说明

### 4.1 配置项

```yaml
# config.yaml

# ... 现有配置 ...

# Web 服务配置
web:
  host: "0.0.0.0"
  port: 8080

  # 诊断模式: gar / hyb / rar
  diagnosis_mode: "hyb"

  # 静态文件目录（可选，默认 dbdiag/web/static）
  static_dir: null
```

---

## 五、实现步骤

### 阶段 1：渲染逻辑抽取（无破坏性改动）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 1.1 | 创建 `DiagnosisRenderer` 类 | `cli/rendering.py`（新增） |
| 1.2 | 从 GARCLI 抽取渲染方法 | `cli/rendering.py` |
| 1.3 | 更新 GARCLI 使用渲染器 | `cli/main.py` |
| 1.4 | 验证现有 CLI 仍正常工作 | 手动测试 |
| 1.5 | 添加渲染器单元测试 | `tests/unit/test_rendering.py` |

### 阶段 2：WebSocket 后端

| 步骤 | 任务 | 文件 |
|------|------|------|
| 2.1 | 创建 WebChatSession 类 | `api/websocket.py`（新增） |
| 2.2 | 实现消息处理逻辑 | `api/websocket.py` |
| 2.3 | 实现 HTML 渲染 | `api/websocket.py` |
| 2.4 | 创建 WebSocket 端点 | `api/websocket.py` |
| 2.5 | 注册端点到 FastAPI | `api/main.py` |
| 2.6 | 添加单元测试 | `tests/unit/test_websocket.py` |

### 阶段 3：前端

| 步骤 | 任务 | 文件 |
|------|------|------|
| 3.1 | 创建静态文件目录 | `web/static/`（新增） |
| 3.2 | 创建 HTML 页面 | `web/static/index.html` |
| 3.3 | 创建 CSS 样式 | `web/static/style.css` |
| 3.4 | 配置静态文件服务 | `api/main.py` |

### 阶段 4：配置与集成

| 步骤 | 任务 | 文件 |
|------|------|------|
| 4.1 | 添加 web 配置项 | `utils/config.py` |
| 4.2 | 更新 config.yaml.example | `config.yaml.example` |
| 4.3 | 添加 CLI 命令启动 web 服务 | `__main__.py` |

### 阶段 5：测试与文档

| 步骤 | 任务 | 文件 |
|------|------|------|
| 5.1 | E2E 测试：单用户流程 | `tests/e2e/test_web.py` |
| 5.2 | E2E 测试：多用户隔离 | `tests/e2e/test_web.py` |
| 5.3 | 更新 design.md | `docs/design.md` |
| 5.4 | 更新 README.md | `README.md` |

---

## 六、测试要点

### 6.1 单元测试

| 测试用例 | 说明 |
|----------|------|
| `test_renderer_status_bar` | 验证状态栏渲染 |
| `test_renderer_recommendation` | 验证现象推荐渲染 |
| `test_renderer_diagnosis` | 验证诊断结果渲染 |
| `test_websocket_message_handling` | 验证消息类型路由 |
| `test_websocket_session_isolation` | 验证每个连接有独立状态 |

### 6.2 集成测试

| 测试用例 | 说明 |
|----------|------|
| `test_websocket_connect` | 验证 WebSocket 连接建立 |
| `test_websocket_welcome` | 验证连接时发送欢迎消息 |
| `test_websocket_diagnosis_flow` | 验证完整诊断流程 |
| `test_websocket_commands` | 验证 /help, /reset, /exit 命令 |

### 6.3 端到端测试

| 测试用例 | 说明 |
|----------|------|
| `test_multi_user_isolation` | 两个用户，验证会话互不干扰 |
| `test_concurrent_diagnosis` | 多个诊断并行执行 |

---

## 七、启动命令

```bash
# 启动 web 服务
python -m dbdiag web

# 指定端口
python -m dbdiag web --port 8080

# 指定 host（允许外部访问）
python -m dbdiag web --host 0.0.0.0 --port 8080
```

---

## 八、开放问题

| 问题 | 当前决策 | 备注 |
|------|----------|------|
| 浏览器兼容性 | 现代浏览器（Chrome, Firefox, Edge） | 需要 WebSocket 支持 |
| 移动端支持 | 暂不优先 | 可后续添加 |
| 会话超时 | 无超时 | 可按需添加 |
| 最大并发用户 | 无限制 | 可按需添加 |
