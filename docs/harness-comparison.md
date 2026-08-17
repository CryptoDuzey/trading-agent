# Trading Agent Mini Harness 与 DeepSeek Harness 对照

本文件是 30 天路线 Day 18 的产物：对照 Trading Agent 自研的 Mini Harness
（`services/api/app/agent/`）与 DeepSeek Harness（`C:\Users\tongd\Desktop\deepseek`
monorepo）的核心模块，说明两份实现的异同，以及 Trading Agent 未来以插件方式接入
DeepSeek Harness 的路径。

## 1. 总览

| 维度 | Trading Agent Mini Harness | DeepSeek Harness |
|---|---|---|
| 语言 / 运行时 | Python + FastAPI（async） | TypeScript monorepo（pnpm workspaces） |
| 目标 | 教学用最小实现，手写每个核心模块 | 生产级 Agent 运行时，插件化、可持久化、可审计 |
| Agent 循环 | `AgentRunner`（`loop.py`）的 `for step` 循环 | `ReactLoopAgent`（`agent-loop/src/agent.ts`）的 turn/step 状态机 |
| 消息模型 | `ModelMessage`（`models.py`） | `Message`（`@deepseek-ai/dsh-llm`） |
| 模型层 | `ModelProvider` Protocol + `DeepSeekProvider` | `@deepseek-ai/dsh-llm` 的 `PreparedLlmCall` / `LlmCallConfig` |
| 工具 | `ToolRegistry`（注册 name → handler） | `@deepseek-ai/dsh-tools` 的 schema + 持久化事件词汇 |
| 状态持久化 | PostgreSQL 表（conversations / messages / agent_runs / agent_events） | Session event log（append-only，`deriveMessages` 重建上下文） |
| Web 通信 | FastAPI SSE 入口（`main.py`） | `apps/web` + `packages/web` / `host` |

## 2. 逐模块对照

### 2.1 模型供应商层

- **Trading Agent**：`app/agent/providers/deepseek.py` 实现 `complete(messages, tools) -> AssistantTurn`，
  只暴露一个统一接口；未配置密钥时回退到 `UnconfiguredProvider`，明确提示而不伪造。
- **DeepSeek Harness**：`@deepseek-ai/dsh-llm` 提供 `PreparedLlmCall`、`LlmCallConfig`、
  `GenerateOptions`、`createAssistantMessage`、`BlockAssembler`、`LlmError`，把请求装配、
  错误链和消息构造拆成独立原语，供上层组合。

**相同点**：都把“模型”抽象成可替换的调用接口，Agent 循环不直接依赖某个具体供应商。
**不同点**：DeepSeek 把装配/错误/消息构造拆得更细，Trading Agent 为了教学收敛成一个 `complete`。

### 2.2 工具注册与执行

- **Trading Agent**：`ToolRegistry.register(name, description, input_model, handler, timeout, permission)`，
  用 Pydantic 模型做参数校验，`execute()` 统一返回 `ToolExecutionResult(ok, output, error, duration_ms)`。
- **DeepSeek Harness**：`@deepseek-ai/dsh-tools` 定义工具 schema 与“持久化事件词汇”
  （`tool/code-dispatch-start` / `tool/code-dispatch`），工具派发结果以 session 事件落盘，
  支持嵌套的 Code Mode 子派发（`run_code` 内的 `<parent>:code:<n>` 子调用）。

**相同点**：工具都有明确的输入 schema 和统一的执行结果，执行轨迹都要求可持久化。
**不同点**：Trading Agent 的轨迹在 `AgentEvent` 数据里随 SSE 流式返回；DeepSeek 把每一次派发
写成 session 事件（append-only log），UI 和持久化都读同一份 log。

### 2.3 Agent Loop

- **Trading Agent**（`loop.py`）：`stream()` 构建 `[system, history, user]` → 循环 `model → tool → model`
  → 最终回答；`max_steps` 保护；`simulate`/`trade` 工具触发 `confirmation_required` 并暂停，
  `resume(confirmation_id)` 从 checkpoint 恢复原地执行。
- **DeepSeek Harness**（`agent-loop/src/agent.ts`）：`ReactLoopAgent` 以 `Inbox` 接收排队消息，
  状态机 `idle / maintenance / running` 跨 turn/step 边界驱动；从 session log
  `deriveMessages` 得到每步上下文，支持 `wake`/`cancel`/维护回合。

**相同点**：都是“模型判断 → 工具执行 → 观察结果 → 继续”的闭环，都有最大步数与暂停/恢复语义。
**不同点**：Trading Agent 是显式 `for` 循环，控制流直白；DeepSeek 是事件驱动的状态机，能处理
并发唤醒、取消和维护任务，复杂度更高但更健壮。

### 2.4 Session / 记忆

- **Trading Agent**：`InMemoryConversationStore` / `PostgresConversationStore` 存消息；`compaction.py`
  实现长对话摘要（摘要 + 游标写回 PostgreSQL）；`ContextManager` 做历史裁剪与 Token 预算。
- **DeepSeek Harness**：`@deepseek-ai/dsh-session` 的 `Session` 是事件日志的真相来源，
  `EpochHeader` / `RequestContext` / `TurnEndReason` 组织回合；另有 `compaction` 包专门做压缩。

**相同点**：都区分“当前会话上下文”与“长期压缩记忆”，都防历史污染当前判断。
**不同点**：Trading Agent 把摘要游标存在数据库列里；DeepSeek 把压缩也作为 session 事件的一部分。

### 2.5 权限与人工确认

- **Trading Agent**：`ToolPermission = read | write | simulate | trade | prohibited`；`simulate`/`trade`
  由确定性代码触发 `confirmation_required`，用户批准后 `resume` 才真正执行。
- **DeepSeek Harness**：权限模型更细，通过 scope / guard / hooks 等包组合实现，
  不把“是否允许”交给 LLM 判断。

**相同点**：两者都坚持“权限由确定性代码决定，不由 LLM 自己决定”。

### 2.6 持久化与审计

- **Trading Agent**：`app/persistence/` 用 SQLAlchemy ORM + Alembic 迁移，表结构显式
  （会话、消息、轨迹、确认票据、恢复点、监控、持仓、计划、订单、复盘、笔记）。
- **DeepSeek Harness**：`@deepseek-ai/dsh-session` 用事件日志做单一真相来源，
  `@deepseek-ai/dsh-storage` 负责落盘；`deriveMessages()` 从 log 重建模型上下文。

**关键差异**：Trading Agent 是“关系表 + 显式状态”；DeepSeek 是“事件溯源 + 派生视图”。
事件溯源更适合重放与审计，Trading Agent 的显式表更适合教学和直接查询。

## 3. 关键架构差异小结

1. **控制流模型**：显式 `for` 循环（Trading Agent） vs 事件驱动状态机（DeepSeek）。
2. **真相来源**：关系表字段（Trading Agent） vs append-only 事件日志（DeepSeek）。
3. **工具轨迹**：随 SSE 流内联返回（Trading Agent） vs 写回 session 事件（DeepSeek）。
4. **语言边界**：Python 服务端（Trading Agent） vs TypeScript 全栈 monorepo（DeepSeek）。
5. **可扩展性**：Trading Agent 用 `register_*_tools` 函数集中装配；DeepSeek 用 scope /
   extensions / skill / plugins 分层注册，插件边界更清晰。

## 4. 以插件方式接入 DeepSeek Harness 的路径

roadmap 约定“正式 Trading Agent 以插件方式运行，不直接魔改 Harness 核心”。基于以上对照，
接入路径是：

1. **数据工具插件**：把 Trading Agent 的 Binance / 持仓 / 风险 / 回测 / 交易工具，用
   `@deepseek-ai/dsh-tools` 的 schema 重新包装成 DeepSeek 工具，复用现有确定性逻辑。
2. **配置与 Skill**：用 `skill` / `extensions` 包声明 Trading Agent 的 system prompt、
   权限分级和工具白名单，不侵入 `agent-loop` 核心。
3. **持久化桥接**：Trading Agent 的 PostgreSQL 表继续保留作为“业务数据”，DeepSeek 的
   session 事件作为“对话轨迹”，两者通过 session_id 关联，而不是强行二选一。
4. **Web 入口**：Trading Agent 现有的 React + SSE 界面可以保留为独立前端，DeepSeek Harness
   通过 `apps/web` / `host` 提供宿主，Trading Agent 作为其中的一个 agent / 插件形态运行。

这份对照用于回答“为什么 Mini Harness 这样写、成熟框架又是怎样组织的”，属于学习与
简历素材，不是接入任务的执行计划。
