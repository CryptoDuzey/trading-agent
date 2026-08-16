import { FormEvent, useState } from "react";

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
  const [lastTrace, setLastTrace] = useState<AgentTraceEvent[]>([]);
  const [detailTab, setDetailTab] = useState<"trace" | "tools">("trace");
  const [detailsOpen, setDetailsOpen] = useState(true);

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
    setDetailTab("trace");
    setDetailsOpen(true);
    setLastTrace([]);

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
          setLastTrace((current) => [...current, traceEvent]);
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
    <main className={`workspace${detailsOpen ? "" : " details-closed"}`}>
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
            <div style={{ marginTop: 18 }}>
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
            </div>
          </aside>
        )}

        <div className="message-list" aria-live="polite">
          {messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>
              <span className="message-role">
                {message.role === "assistant" ? "AGENT" : "YOU"}
              </span>
              <div className="message-body">
                <div className="message-content">
                  {message.content || <span className="typing">正在思考…</span>}
                </div>
              </div>
            </article>
          ))}
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
              value={input}
              onChange={(event) => setInput(event.target.value)}
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

      <aside className="details-panel" aria-label="详情面板">
        <header className="details-header">
          <div className="details-tabs">
            <button
              type="button"
              className={detailTab === "trace" ? "active" : ""}
              onClick={() => setDetailTab("trace")}
            >
              执行
            </button>
            <button
              type="button"
              className={detailTab === "tools" ? "active" : ""}
              onClick={() => {
                setDetailTab("tools");
                if (toolsList.length === 0) void openSettings();
              }}
            >
              工具
            </button>
          </div>
          <button
            className="icon-button"
            type="button"
            aria-label="关闭详情面板"
            onClick={() => setDetailsOpen(false)}
          >
            ×
          </button>
        </header>

        {detailTab === "trace" ? (
          <div className="trajectory">
            {lastTrace.length === 0 ? (
              <p className="task-empty">发送一条消息后，这里会展示 Agent 的执行过程。</p>
            ) : (
              <ol className="trajectory-list">
                {lastTrace.map((traceEvent) => {
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
            )}
          </div>
        ) : (
          <div className="tools-catalogue">
            {toolsLoading ? (
              <p className="task-empty">正在加载工具列表…</p>
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
        )}
      </aside>
    </main>
  );
}

export default App;
