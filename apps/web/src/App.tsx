import {
  FormEvent,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import "./styles.css";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  trace?: AgentTraceEvent[];
};

type StreamEvent = {
  content?: string;
};

type AgentTraceEvent = {
  type: string;
  run_id: string;
  sequence: number;
  step: number;
  data: Record<string, unknown>;
};

type AlertTask = {
  id: string;
  market: string;
  symbol: string;
  condition: "price_above" | "price_below";
  threshold: string;
  status: "active" | "paused" | "completed" | "failed";
  notification_channel: "site" | "feishu";
  trigger_count: number;
};

type ToolInfo = { name: string; description: string };

type PositionRow = {
  symbol: string;
  side: string;
  quantity: string;
  market: string;
};

type PlanRow = {
  symbol: string;
  side: string;
  status: string;
};

const SESSION_KEY = "trading-agent-session-id";
const API_KEY = "trading-agent-api-key";
const MODEL_KEY = "trading-agent-model";

const MODEL_OPTIONS = [
  { value: "deepseek-v4-flash", label: "V4 Flash" },
  { value: "deepseek-v4-pro", label: "V4 Pro" },
  { value: "deepseek-chat", label: "Chat" },
  { value: "deepseek-reasoner", label: "Reasoner" },
];

const starterPrompts = [
  "分析 BTC 当前 15 分钟走势",
  "扫描 Binance 异常放量币种",
  "检查我的持仓风险",
];

const initialMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "我是 Trading Agent，一个对话式交易研究助手。你可以让我查询行情、分析风险、回测信号或创建监控任务。当前版本只做研究分析，不会执行真实交易。",
  },
];

async function readEventStream(
  response: Response,
  onDelta: (content: string) => void,
  onAgentEvent: (event: AgentTraceEvent) => void,
) {
  if (!response.ok || !response.body) {
    throw new Error("服务暂时不可用，请稍后重试。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const eventName = block
        .split("\n")
        .find((line) => line.startsWith("event: "))
        ?.slice(7);
      const dataLine = block
        .split("\n")
        .find((line) => line.startsWith("data: "));
      if (!dataLine) continue;

      const event = JSON.parse(dataLine.slice(6)) as StreamEvent;
      if (eventName === "delta" && event.content) onDelta(event.content);
      if (eventName === "agent_event") {
        onAgentEvent(event as AgentTraceEvent);
      }
    }

    if (done) break;
  }
}

function describeTraceEvent(event: AgentTraceEvent) {
  const toolName = typeof event.data.name === "string" ? event.data.name : "未知工具";
  const labels: Record<string, string> = {
    run_started: "开始理解任务",
    model_started: `模型判断 · 第 ${event.step} 步`,
    tool_started: `调用工具：${toolName}`,
    tool_finished: `工具完成：${toolName}`,
    confirmation_required: `等待确认：${toolName}`,
    run_paused: "任务已暂停",
    run_resumed: "任务已恢复",
    answer_delta: "整理最终回答",
    run_completed: "任务完成",
    run_failed: "任务失败",
  };
  return labels[event.type] ?? event.type;
}

type ToolOutput = {
  source?: unknown;
  candle_count?: unknown;
  scanned_count?: unknown;
  total_samples?: unknown;
  observed_at?: unknown;
  limitation?: unknown;
  positions?: unknown;
  plans?: unknown;
  orders?: unknown;
  notes?: unknown;
  events?: unknown;
  items?: unknown;
};

function extractEvidence(event: AgentTraceEvent): string[] {
  if (event.type !== "tool_finished") return [];
  const output = (event.data as { output?: ToolOutput }).output;
  if (!output || typeof output !== "object") return [];

  const evidence: string[] = [];
  if (typeof output.source === "string") evidence.push(`数据来源：${output.source}`);
  if (typeof output.candle_count === "number") evidence.push(`使用 ${output.candle_count} 根 K 线`);
  if (typeof output.scanned_count === "number") evidence.push(`扫描 ${output.scanned_count} 个标的`);
  if (typeof output.total_samples === "number") evidence.push(`历史样本 ${output.total_samples} 个`);
  if (typeof output.observed_at === "string") {
    evidence.push(`观测时间：${new Date(output.observed_at).toLocaleString()}`);
  }
  for (const key of ["positions", "plans", "orders", "notes", "events", "items"] as const) {
    if (Array.isArray(output[key])) {
      evidence.push(`${key === "positions" ? "持仓" : key} ${output[key].length} 条`);
    }
  }
  if (typeof output.limitation === "string" && output.limitation) {
    evidence.push(`限制说明：${output.limitation}`);
  }
  return evidence;
}

function getOrCreateSessionId() {
  const stored = localStorage.getItem(SESSION_KEY);
  if (stored) return stored;
  const created = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, created);
  return created;
}

const taskStatusLabels: Record<AlertTask["status"], string> = {
  active: "监控中",
  paused: "已暂停",
  completed: "已触发",
  failed: "检查失败",
};

function clampWidth(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.round(value)));
}

function App() {
  const [sessionId] = useState(getOrCreateSessionId);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tasks, setTasks] = useState<AlertTask[]>([]);
  const [taskPanelOpen, setTaskPanelOpen] = useState(false);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [apiKey, setApiKey] = useState(() => localStorage.getItem(API_KEY) ?? "");
  const [model, setModel] = useState(
    () => localStorage.getItem(MODEL_KEY) ?? "deepseek-v4-flash",
  );
  const [toolsList, setToolsList] = useState<ToolInfo[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef(0);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [insightsOpen, setInsightsOpen] = useState(false);
  const [insightsWidth, setInsightsWidth] = useState(320);
  const insightsDragStart = useRef(0);

  useEffect(() => {
    const el = messageEndRef.current;
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const loadInsights = async () => {
    try {
      const [positionResponse, planResponse] = await Promise.all([
        fetch(`/api/positions?owner_id=${encodeURIComponent(sessionId)}`),
        fetch(`/api/plans?owner_id=${encodeURIComponent(sessionId)}`),
      ]);
      if (positionResponse.ok) setPositions(await positionResponse.json());
      if (planResponse.ok) setPlans(await planResponse.json());
    } catch {
      // 概览数据加载失败不阻塞界面
    }
  };

  const loadTasks = async () => {
    setTaskPanelOpen(true);
    setSettingsOpen(false);
    setTasksLoading(true);
    setTaskError(null);
    try {
      const response = await fetch(
        `/api/alerts?owner_id=${encodeURIComponent(sessionId)}`,
      );
      if (!response.ok) throw new Error("监控任务暂时无法读取。");
      setTasks((await response.json()) as AlertTask[]);
    } catch (caughtError) {
      setTaskError(
        caughtError instanceof Error ? caughtError.message : "读取任务失败。",
      );
    } finally {
      setTasksLoading(false);
    }
  };

  const toggleTaskPanel = () => {
    if (taskPanelOpen) {
      setTaskPanelOpen(false);
      return;
    }
    void loadTasks();
  };

  const changeTaskStatus = async (task: AlertTask) => {
    const action = task.status === "active" ? "pause" : "resume";
    setTaskError(null);
    try {
      const response = await fetch(
        `/api/alerts/${task.id}/${action}?owner_id=${encodeURIComponent(sessionId)}`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error("任务状态修改失败。");
      const updated = (await response.json()) as AlertTask;
      setTasks((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (caughtError) {
      setTaskError(
        caughtError instanceof Error ? caughtError.message : "任务状态修改失败。",
      );
    }
  };

  const openSettings = async () => {
    setSettingsOpen(true);
    setTaskPanelOpen(false);
    if (toolsList.length === 0) {
      setToolsLoading(true);
      try {
        const response = await fetch("/api/tools");
        if (response.ok) setToolsList(await response.json());
      } catch {
        // 工具列表加载失败不阻塞设置面板
      } finally {
        setToolsLoading(false);
      }
    }
  };

  const saveSettings = () => {
    localStorage.setItem(API_KEY, apiKey.trim());
    localStorage.setItem(MODEL_KEY, model);
    setSettingsOpen(false);
  };

  const submitMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = input.trim();
    if (!message || isSending) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: message,
    };
    const assistantId = crypto.randomUUID();

    setMessages((current) => [
      ...current,
      userMessage,
      { id: assistantId, role: "assistant", content: "" },
    ]);
    setInput("");
    setError(null);
    setIsSending(true);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: sessionId,
          api_key: apiKey.trim() || undefined,
          model: model || undefined,
        }),
      });

      await readEventStream(
        response,
        (content) => {
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId
                ? { ...item, content: item.content + content }
                : item,
            ),
          );
        },
        (traceEvent) => {
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId
                ? { ...item, trace: [...(item.trace ?? []), traceEvent] }
                : item,
            ),
          );
        },
      );
    } catch (caughtError) {
      setMessages((current) =>
        current.filter((item) => item.id !== assistantId),
      );
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "发生未知错误，请稍后重试。",
      );
    } finally {
      setIsSending(false);
    }
  };

  const useStarterPrompt = (prompt: string) => setInput(prompt);

  return (
    <main
      className={`workspace${dragging ? " dragging" : ""}`}
      style={
        {
          gridTemplateColumns: insightsOpen
            ? `${sidebarWidth}px minmax(0, 1fr) ${insightsWidth}px`
            : `${sidebarWidth}px minmax(0, 1fr) 0px`,
          "--sidebar-width": `${sidebarWidth}px`,
          "--insights-width": `${insightsWidth}px`,
        } as CSSProperties
      }
    >
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark" aria-hidden="true">
            TA
          </div>
          <div>
            <p className="overline">AI TRADING DESK</p>
            <h1 className="brand-name">
              Trading<em>Agent</em>
            </h1>
          </div>
        </div>

        <section className="workspace-list">
          <p className="overline">WORKSPACE</p>
          <button className="workspace-item active" type="button">
            <span className="ws-dot" />
            交易研究
          </button>
        </section>

        <section className="market-status">
          <div className="status-heading">
            <span className="live-dot" />
            <span>分析服务在线</span>
          </div>
          <p>Binance · 只读研究模式</p>
        </section>

        <footer>
          <span className="safety-badge">真实交易已锁定</span>
          <p>所有结论仅供研究，不构成投资建议。</p>
        </footer>
      </aside>

      <section className="chat-panel" aria-label="交易 Agent 对话">
        <header className="chat-header">
          <div>
            <p className="overline">CONVERSATION 01</p>
            <h2>今天想研究什么？</h2>
          </div>
          <div className="header-actions">
            <select
              className="model-select"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              aria-label="选择模型"
            >
              {MODEL_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
              {model &&
                !MODEL_OPTIONS.some((option) => option.value === model) && (
                  <option value={model}>{model}</option>
                )}
            </select>
            <button
              className="icon-button"
              type="button"
              aria-label="打开任务面板"
              onClick={toggleTaskPanel}
            >
              任务 <span>{tasks.filter((task) => task.status === "active").length}</span>
            </button>
            <button
              className="icon-button"
              type="button"
              aria-label="切换概览面板"
              onClick={() => {
                setInsightsOpen((open) => !open);
                if (!insightsOpen) void loadInsights();
              }}
            >
              概览
            </button>
            <button
              className="icon-button"
              type="button"
              aria-label="打开设置"
              onClick={() => {
                if (settingsOpen) {
                  setSettingsOpen(false);
                } else {
                  void openSettings();
                }
              }}
            >
              设置
            </button>
          </div>
        </header>

        {taskPanelOpen && (
          <aside className="overlay-panel" aria-label="监控任务面板">
            <header>
              <div>
                <p className="overline">DELEGATED TASKS</p>
                <h3>监控任务</h3>
              </div>
              <button type="button" onClick={() => setTaskPanelOpen(false)} aria-label="关闭任务面板">
                ×
              </button>
            </header>
            {tasksLoading && <p className="task-empty">正在读取任务…</p>}
            {taskError && <p className="task-error">{taskError}</p>}
            {!tasksLoading && !taskError && tasks.length === 0 && (
              <p className="task-empty">还没有任务。你可以在对话中让我创建价格提醒。</p>
            )}
            <div className="task-list">
              {tasks.map((task) => (
                <article className="task-card" key={task.id}>
                  <div className="task-card-heading">
                    <strong>{task.symbol}</strong>
                    <span className={`task-status ${task.status}`}>
                      {taskStatusLabels[task.status]}
                    </span>
                  </div>
                  <p>
                    价格{task.condition === "price_below" ? "低于" : "高于"} {task.threshold}
                  </p>
                  <small>{task.market} · {task.notification_channel === "feishu" ? "飞书" : "站内"}</small>
                  {(task.status === "active" || task.status === "paused") && (
                    <button
                      type="button"
                      aria-label={`${task.status === "active" ? "暂停" : "恢复"} ${task.symbol}`}
                      onClick={() => void changeTaskStatus(task)}
                    >
                      {task.status === "active" ? "暂停" : "恢复"}
                    </button>
                  )}
                </article>
              ))}
            </div>
          </aside>
        )}

        {settingsOpen && (
          <aside className="overlay-panel" aria-label="设置面板">
            <header>
              <div>
                <p className="overline">SETTINGS</p>
                <h3>模型与密钥</h3>
              </div>
              <button type="button" onClick={() => setSettingsOpen(false)} aria-label="关闭设置">
                ×
              </button>
            </header>
            <div style={{ marginTop: 16 }}>
              <div className="field">
                <label htmlFor="api-key">DeepSeek API Key</label>
                <input
                  id="api-key"
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder="sk-..."
                  autoComplete="off"
                />
                <p className="field-hint">密钥只存在你的浏览器里，随请求发送，不会写进代码仓库。</p>
              </div>
              <div className="field">
                <label htmlFor="model-name">模型</label>
                <select
                  id="model-name"
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                >
                  {MODEL_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                  {model &&
                    !MODEL_OPTIONS.some((option) => option.value === model) && (
                      <option value={model}>{model}</option>
                    )}
                </select>
              </div>
              <button className="primary-button" type="button" onClick={saveSettings}>
                保存设置
              </button>
              <p className="settings-note">
                没有密钥时系统仍可启动，但会明确提示模型未配置，不会伪造行情分析。
              </p>
              <div className="field tools-block">
                <label>可用工具（{toolsList.length}）</label>
                {toolsLoading ? (
                  <p className="field-hint">正在加载工具列表…</p>
                ) : (
                  <ul className="tools-list">
                    {toolsList.map((tool) => (
                      <li key={tool.name}>
                        <strong>{tool.name}</strong>
                        <span>{tool.description}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </aside>
        )}

        <div className="message-list" aria-live="polite">
          {messages.map((message) => (
            <div
              className={`message ${message.role}`}
              key={message.id}
            >
              {message.role === "user" ? (
                <div className="user-bubble">{message.content}</div>
              ) : (
                <div className="assistant-content">
                  {message.content || <span className="typing">正在思考…</span>}
                </div>
              )}
              {message.trace && message.trace.length > 0 && (
                <details className="execution-trace">
                  <summary>执行过程 · {message.trace.length} 条</summary>
                  <ol>
                    {message.trace.map((traceEvent) => {
                      const evidence = extractEvidence(traceEvent);
                      return (
                        <li key={`${traceEvent.run_id}-${traceEvent.sequence}`}>
                          <span>{describeTraceEvent(traceEvent)}</span>
                          <small>步骤 {traceEvent.step}</small>
                          {evidence.length > 0 && (
                            <ul className="trace-evidence">
                              {evidence.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                </details>
              )}
            </div>
          ))}
          <div ref={messageEndRef} />
        </div>

        {messages.length === 1 && (
          <div className="starter-grid" aria-label="快捷问题">
            {starterPrompts.map((prompt) => (
              <button key={prompt} type="button" onClick={() => useStarterPrompt(prompt)}>
                <span>↗</span>
                {prompt}
              </button>
            ))}
          </div>
        )}

        <div className="composer-wrap">
          {error && <p className="error-message">{error}</p>}
          <form className="composer" onSubmit={submitMessage}>
            <label className="sr-only" htmlFor="trade-question">
              交易问题
            </label>
            <textarea
              id="trade-question"
              ref={textareaRef}
              value={input}
              onChange={(event) => {
                setInput(event.target.value);
                const el = textareaRef.current;
                if (el) {
                  el.style.height = "auto";
                  el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
                }
              }}
              placeholder="询问行情、风险、回测，或委托一个监控任务…"
              rows={1}
            />
            <button
              className="send-button"
              type="submit"
              aria-label={isSending ? "正在发送" : "发送消息"}
              disabled={!input.trim() || isSending}
            >
              {isSending ? "…" : "↑"}
            </button>
          </form>
          <p className="composer-hint">点击箭头发送 · 首月不执行真实交易</p>
        </div>
      </section>

      {insightsOpen && (
      <aside className="insights-panel" aria-label="消息面概览">
        <header className="insights-header">
          <div>
            <p className="overline">MARKET OVERVIEW</p>
            <h3>消息面</h3>
          </div>
          <button
            type="button"
            aria-label="关闭概览面板"
            onClick={() => setInsightsOpen(false)}
          >
            ×
          </button>
        </header>
        <div className="insights-body">
          <section className="insight-card">
            <h4>会话</h4>
            <div className="insight-stats">
              <span>{messages.length} 条消息</span>
              <span>
                {messages.reduce(
                  (count, message) => count + (message.trace?.length ?? 0),
                  0,
                )}{" "}
                次工具调用
              </span>
            </div>
          </section>

          <section className="insight-card">
            <h4>持仓 · {positions.length}</h4>
            {positions.length === 0 ? (
              <p className="insight-empty">暂无持仓，可让 Agent 帮你录入。</p>
            ) : (
              <ul className="insight-list">
                {positions.map((position) => (
                  <li key={`${position.symbol}-${position.side}`}>
                    <strong>{position.symbol}</strong>
                    <span
                      className={
                        position.side === "long" ? "side-long" : "side-short"
                      }
                    >
                      {position.side === "long" ? "多" : "空"} {position.quantity}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="insight-card">
            <h4>
              交易计划 ·{" "}
              {plans.filter((plan) => plan.status === "planned").length}
            </h4>
            {plans.filter((plan) => plan.status === "planned").length === 0 ? (
              <p className="insight-empty">暂无待执行计划。</p>
            ) : (
              <ul className="insight-list">
                {plans
                  .filter((plan) => plan.status === "planned")
                  .map((plan, index) => (
                    <li key={`${plan.symbol}-${index}`}>
                      <strong>{plan.symbol}</strong>
                      <span
                        className={
                          plan.side === "long" ? "side-long" : "side-short"
                        }
                      >
                        {plan.side === "long" ? "多" : "空"}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </section>

          <section className="insight-card">
            <h4>
              监控任务 · {tasks.filter((task) => task.status === "active").length}
            </h4>
            {tasks.filter((task) => task.status === "active").length === 0 ? (
              <p className="insight-empty">暂无监控任务。</p>
            ) : (
              <ul className="insight-list">
                {tasks
                  .filter((task) => task.status === "active")
                  .map((task) => (
                    <li key={task.id}>
                      <strong>{task.symbol}</strong>
                      <span>
                        {task.condition === "price_below" ? "跌破" : "突破"}{" "}
                        {task.threshold}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </section>
        </div>
      </aside>
      )}

      <div
        className="drag-handle sidebar"
        data-dragging={dragging || undefined}
        onPointerDown={(event) => {
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          dragStart.current = event.clientX;
          setDragging(true);
        }}
        onPointerMove={(event) => {
          if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
          const dx = event.clientX - dragStart.current;
          dragStart.current = event.clientX;
          setSidebarWidth((width) => clampWidth(width + dx, 200, 460));
        }}
        onPointerUp={() => setDragging(false)}
      />
      {insightsOpen && (
        <div
          className="drag-handle insights"
          onPointerDown={(event) => {
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            insightsDragStart.current = event.clientX;
          }}
          onPointerMove={(event) => {
            if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
            const dx = event.clientX - insightsDragStart.current;
            insightsDragStart.current = event.clientX;
            setInsightsWidth((width) => clampWidth(width - dx, 280, 480));
          }}
        />
      )}
    </main>
  );
}

export default App;
