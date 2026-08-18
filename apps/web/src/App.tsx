import {
  FormEvent,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import "./styles.css";
import KlineChart, { type Candle } from "./KlineChart";
import ReactMarkdown from "react-markdown";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
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

type TickerRow = {
  symbol: string;
  price: string;
};

const SESSION_KEY = "trading-agent-session-id";
const API_KEY = "trading-agent-api-key";
const MODEL_KEY = "trading-agent-model";
const THEME_KEY = "trading-agent-theme";

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

const CAPABILITIES = [
  { icon: "📊", name: "行情", count: 4 },
  { icon: "📈", name: "技术分析", count: 5 },
  { icon: "💼", name: "交易", count: 7 },
  { icon: "🛡", name: "风险", count: 3 },
  { icon: "📚", name: "知识库", count: 3 },
  { icon: "📰", name: "消息", count: 4 },
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

function extractKlines(trace: AgentTraceEvent[]): Candle[] {
  const klineEvent = trace.find(
    (event) =>
      event.type === "tool_finished" && event.data.name === "get_klines",
  );
  if (!klineEvent) return [];
  const output = (klineEvent.data as { output?: { candles?: Candle[] } }).output;
  return output?.candles ?? [];
}

type ScanOpportunity = {
  symbol: string;
  last_price: string;
  price_change_percent_24h: number;
  quote_volume_24h: number;
  anomaly_score: number;
  signals: string[];
};

function extractScanResults(trace: AgentTraceEvent[]): ScanOpportunity[] {
  const scanEvent = trace.find(
    (event) =>
      event.type === "tool_finished" && event.data.name === "scan_binance_market",
  );
  if (!scanEvent) return [];
  const output = (
    scanEvent.data as { output?: { opportunities?: ScanOpportunity[] } }
  ).output;
  return output?.opportunities ?? [];
}

type BacktestResult = {
  symbol: string;
  total_samples: number;
  win_rate_percent: number;
  average_return_percent: number;
  max_drawdown_percent: number;
};

function extractBacktestResult(trace: AgentTraceEvent[]): BacktestResult | null {
  const event = trace.find(
    (item) =>
      item.type === "tool_finished" && item.data.name === "run_signal_backtest",
  );
  if (!event) return null;
  const output = event.data.output as Partial<BacktestResult> | undefined;
  if (!output || typeof output.total_samples !== "number") return null;
  return {
    symbol: output.symbol ?? "",
    total_samples: output.total_samples,
    win_rate_percent: output.win_rate_percent ?? 0,
    average_return_percent: output.average_return_percent ?? 0,
    max_drawdown_percent: output.max_drawdown_percent ?? 0,
  };
}

type PositionRiskRow = {
  symbol: string;
  side: string;
  unrealized_pnl: number;
  return_on_margin_percent: number;
};

type PortfolioRiskResult = {
  risk_level: string;
  total_unrealized_pnl: number;
  positions: PositionRiskRow[];
};

function extractPortfolioRisk(trace: AgentTraceEvent[]): PortfolioRiskResult | null {
  const event = trace.find(
    (item) =>
      item.type === "tool_finished" && item.data.name === "analyze_portfolio_risk",
  );
  if (!event) return null;
  const output = event.data.output as
    | {
        risk_level?: string;
        total_unrealized_pnl?: number;
        positions?: Array<{
          symbol: string;
          side: string;
          unrealized_pnl: number;
          return_on_margin_percent: number;
        }>;
      }
    | undefined;
  if (!output || !Array.isArray(output.positions)) return null;
  return {
    risk_level: output.risk_level ?? "unknown",
    total_unrealized_pnl: output.total_unrealized_pnl ?? 0,
    positions: output.positions.map((position) => ({
      symbol: position.symbol,
      side: position.side,
      unrealized_pnl: position.unrealized_pnl,
      return_on_margin_percent: position.return_on_margin_percent,
    })),
  };
}

function BacktestCard({ result }: { result: BacktestResult }) {
  return (
    <div className="backtest-card">
      <div className="backtest-title">
        {result.symbol || "信号"} 回测
      </div>
      <div className="metric-grid">
        <div className="metric">
          <span className="metric-value">{result.total_samples}</span>
          <span className="metric-label">样本数</span>
        </div>
        <div className="metric">
          <span className="metric-value">
            {result.win_rate_percent.toFixed(1)}%
          </span>
          <span className="metric-label">胜率</span>
        </div>
        <div className="metric">
          <span
            className={`metric-value ${
              result.average_return_percent >= 0 ? "scan-up" : "scan-down"
            }`}
          >
            {result.average_return_percent >= 0 ? "+" : ""}
            {result.average_return_percent.toFixed(2)}%
          </span>
          <span className="metric-label">平均收益</span>
        </div>
        <div className="metric">
          <span className="metric-value">
            {result.max_drawdown_percent.toFixed(2)}%
          </span>
          <span className="metric-label">最大回撤</span>
        </div>
      </div>
    </div>
  );
}

type TradingPlanRow = {
  symbol: string;
  side: string;
  entry_low: string;
  entry_high: string;
  stop_loss: string;
  take_profit: string;
  position_size: string;
  risk_note: string;
};

function extractTradingPlans(trace: AgentTraceEvent[]): TradingPlanRow[] {
  const event = trace.find(
    (item) =>
      item.type === "tool_finished" && item.data.name === "create_trading_plan",
  );
  if (!event) return [];
  const output = event.data.output as Partial<TradingPlanRow> | undefined;
  if (!output || !output.symbol) return [];
  return [
    {
      symbol: output.symbol,
      side: output.side ?? "long",
      entry_low: output.entry_low ?? "",
      entry_high: output.entry_high ?? "",
      stop_loss: output.stop_loss ?? "",
      take_profit: output.take_profit ?? "",
      position_size: output.position_size ?? "",
      risk_note: output.risk_note ?? "",
    },
  ];
}

function TradingPlanCard({ plan }: { plan: TradingPlanRow }) {
  return (
    <div className="plan-card">
      <div className="plan-head">
        <span className="plan-symbol">{plan.symbol}</span>
        <span
          className={`plan-side ${
            plan.side === "long" ? "scan-up" : "scan-down"
          }`}
        >
          {plan.side === "long" ? "做多" : "做空"}
        </span>
      </div>
      <div className="plan-fields">
        <div className="plan-field">
          <span className="plan-field-label">入场区间</span>
          <span className="plan-field-value">
            {plan.entry_low} ~ {plan.entry_high}
          </span>
        </div>
        <div className="plan-field">
          <span className="plan-field-label">止损</span>
          <span className="plan-field-value">{plan.stop_loss}</span>
        </div>
        <div className="plan-field">
          <span className="plan-field-label">止盈</span>
          <span className="plan-field-value">{plan.take_profit}</span>
        </div>
        <div className="plan-field">
          <span className="plan-field-label">仓位</span>
          <span className="plan-field-value">{plan.position_size}</span>
        </div>
      </div>
      {plan.risk_note && (
        <p className="plan-note">{plan.risk_note}</p>
      )}
    </div>
  );
}

function PortfolioRiskCard({ result }: { result: PortfolioRiskResult }) {
  const levelLabel: Record<string, string> = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
    critical: "严重风险",
    unknown: "未知",
  };
  return (
    <div className="portfolio-card">
      <div className="portfolio-head">
        <span className={`risk-badge risk-${result.risk_level}`}>
          {levelLabel[result.risk_level] ?? result.risk_level}
        </span>
        <span
          className={`portfolio-total ${
            result.total_unrealized_pnl >= 0 ? "scan-up" : "scan-down"
          }`}
        >
          {result.total_unrealized_pnl >= 0 ? "+" : ""}
          {result.total_unrealized_pnl.toLocaleString("en-US", {
            maximumFractionDigits: 2,
          })}{" "}
          盈亏
        </span>
      </div>
      <ul className="position-list">
        {result.positions.map((position) => (
          <li key={`${position.symbol}-${position.side}`}>
            <span className="position-symbol">{position.symbol}</span>
            <span
              className={`position-side ${
                position.side === "long" ? "scan-up" : "scan-down"
              }`}
            >
              {position.side === "long" ? "多" : "空"}
            </span>
            <span
              className={`position-pnl ${
                position.unrealized_pnl >= 0 ? "scan-up" : "scan-down"
              }`}
            >
              {position.unrealized_pnl >= 0 ? "+" : ""}
              {position.unrealized_pnl.toFixed(2)}
            </span>
            <span
              className={`position-return ${
                position.return_on_margin_percent >= 0 ? "scan-up" : "scan-down"
              }`}
            >
              {position.return_on_margin_percent >= 0 ? "+" : ""}
              {position.return_on_margin_percent.toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function computeToolUsage(messages: ChatMessage[]): Record<string, number> {
  const usage: Record<string, number> = {};
  for (const message of messages) {
    for (const event of message.trace ?? []) {
      if (event.type === "tool_finished") {
        const name = String(event.data.name);
        usage[name] = (usage[name] ?? 0) + 1;
      }
    }
  }
  return usage;
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
  const [sessionId, setSessionId] = useState(getOrCreateSessionId);
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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef(0);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [tickers, setTickers] = useState<TickerRow[]>([]);
  const [sessions, setSessions] = useState<
    { id: string; message_count: number }[]
  >([]);
  const [insightsOpen, setInsightsOpen] = useState(false);
  const [insightsWidth, setInsightsWidth] = useState(320);
  const insightsDragStart = useRef(0);
  const [listening, setListening] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem(THEME_KEY) as "light" | "dark") ?? "light",
  );
  const [feedback, setFeedback] = useState<Record<string, "up" | "down">>({});
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((open) => !open);
        setCommandQuery("");
      }
      if (event.key === "Escape") {
        setCommandOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    document.body.classList.toggle("dark", theme === "dark");
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    const el = messageEndRef.current;
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const loadInsights = async () => {
    try {
      const [positionResponse, planResponse, tickerResponse] = await Promise.all([
        fetch(`/api/positions?owner_id=${encodeURIComponent(sessionId)}`),
        fetch(`/api/plans?owner_id=${encodeURIComponent(sessionId)}`),
        fetch("/api/market-tickers"),
      ]);
      if (positionResponse.ok) setPositions(await positionResponse.json());
      if (planResponse.ok) setPlans(await planResponse.json());
      if (tickerResponse.ok) setTickers(await tickerResponse.json());
    } catch {
      // 概览数据加载失败不阻塞界面
    }
  };

  const loadSessions = async () => {
    try {
      const response = await fetch("/api/sessions");
      if (response.ok) {
        setSessions(await response.json());
      }
    } catch {
      // 会话列表加载失败不阻塞界面
    }
  };

  const newSession = () => {
    const id = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, id);
    setSessionId(id);
    setMessages(initialMessages);
    setPositions([]);
    setPlans([]);
    void loadSessions();
  };

  const switchSession = (id: string) => {
    if (id === sessionId) return;
    localStorage.setItem(SESSION_KEY, id);
    setSessionId(id);
    setMessages(initialMessages);
    setPositions([]);
    setPlans([]);
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

  const sendMessage = async (message: string) => {
    if (!message || isSending) return;
    const assistantId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      { id: assistantId, role: "assistant", content: "" },
    ]);
    setError(null);
    setIsSending(true);

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
            current.map((item) => {
              if (item.id !== assistantId) return item;
              if (traceEvent.type === "reasoning_delta") {
                const delta = String(traceEvent.data.content ?? "");
                return { ...item, reasoning: (item.reasoning ?? "") + delta };
              }
              return { ...item, trace: [...(item.trace ?? []), traceEvent] };
            }),
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
      void loadSessions();
    }
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
    setMessages((current) => [...current, userMessage]);
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    await sendMessage(message);
  };

  const regenerate = async (assistantId: string) => {
    if (isSending) return;
    const index = messages.findIndex((item) => item.id === assistantId);
    if (index < 0) return;
    let userText = "";
    for (let i = index - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        userText = messages[i].content;
        break;
      }
    }
    if (!userText) return;
    setMessages((current) => current.filter((item) => item.id !== assistantId));
    await sendMessage(userText);
  };

  const toggleFeedback = (id: string, value: "up" | "down") => {
    setFeedback((current) => {
      const next = { ...current };
      if (next[id] === value) {
        delete next[id];
      } else {
        next[id] = value;
      }
      return next;
    });
  };

  const clearConversation = () => {
    setMessages(initialMessages);
    setFeedback({});
  };

  const useStarterPrompt = (prompt: string) => setInput(prompt);

  const startListening = () => {
    const SpeechRecognition =
      (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: unknown })
        .webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setError("当前浏览器不支持语音输入，请手动输入。");
      return;
    }
    const recognition = new (SpeechRecognition as new () => {
      lang: string;
      interimResults: boolean;
      onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } } }) => void) | null;
      onend: (() => void) | null;
      onerror: (() => void) | null;
      start: () => void;
    })();
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      setInput((current) => (current ? `${current} ${transcript}` : transcript));
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    setListening(true);
    recognition.start();
  };

  const commands = [
    { id: "new", icon: "＋", label: "新建会话", run: newSession },
    {
      id: "theme",
      icon: theme === "light" ? "🌙" : "☀️",
      label: "切换主题",
      run: () => setTheme((t) => (t === "light" ? "dark" : "light")),
    },
    {
      id: "insights",
      icon: "▤",
      label: "打开概览面板",
      run: () => {
        setInsightsOpen(true);
        void loadInsights();
      },
    },
    { id: "tasks", icon: "◷", label: "打开监控任务", run: () => void loadTasks() },
    { id: "settings", icon: "⚙", label: "打开设置", run: () => void openSettings() },
    { id: "clear", icon: "⌫", label: "清空对话", run: clearConversation },
  ];

  const filteredCommands = commands.filter((command) =>
    command.label.toLowerCase().includes(commandQuery.toLowerCase()),
  );

  return (
    <main
      className={`workspace${dragging ? " dragging" : ""}${sidebarCollapsed ? " sidebar-collapsed" : ""}`}
      style={
        {
          gridTemplateColumns: `${sidebarCollapsed ? "0px" : `${sidebarWidth}px`} minmax(0, 1fr) ${insightsOpen ? `${insightsWidth}px` : "0px"}`,
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
          <div className="workspace-list-head">
            <p className="overline">WORKSPACE</p>
            <button
              className="new-session-btn"
              type="button"
              aria-label="新建会话"
              onClick={newSession}
            >
              +
            </button>
          </div>
          {sessions.length === 0 ? (
            <button className="workspace-item active" type="button">
              <span className="ws-dot" />
              交易研究
            </button>
          ) : (
            sessions.map((item) => (
              <button
                className={`workspace-item${item.id === sessionId ? " active" : ""}`}
                type="button"
                key={item.id}
                onClick={() => switchSession(item.id)}
              >
                <span className="ws-dot" />
                {item.id.slice(0, 8)} · {item.message_count}
              </button>
            ))
          )}
        </section>

        <section className="market-status">
          <div className="status-heading">
            <span className="live-dot" />
            <span>分析服务在线</span>
          </div>
          <p>Binance · 只读研究模式</p>
        </section>

        <section className="capability-list">
          <p className="overline">能力</p>
          {CAPABILITIES.map((capability) => (
            <div className="capability-item" key={capability.name}>
              <span className="capability-icon">{capability.icon}</span>
              <span className="capability-name">{capability.name}</span>
              <span className="capability-count">{capability.count}</span>
            </div>
          ))}
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
            <button
              className="icon-button"
              type="button"
              aria-label={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
              onClick={() => setSidebarCollapsed((c) => !c)}
            >
              {sidebarCollapsed ? "◧" : "◨"}
            </button>
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
            <button
              className="icon-button"
              type="button"
              aria-label="切换主题"
              onClick={() =>
                setTheme((current) => (current === "light" ? "dark" : "light"))
              }
            >
              {theme === "light" ? "🌙" : "☀️"}
            </button>
            <button
              className="icon-button"
              type="button"
              aria-label="清空对话"
              onClick={clearConversation}
            >
              清空
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
                <>
                  {message.reasoning && (
                    <details className="reasoning-box">
                      <summary>思考过程</summary>
                      <div className="reasoning-content">
                        {message.reasoning}
                      </div>
                    </details>
                  )}
                  <div className="assistant-content">
                    {message.content ? (
                      <ReactMarkdown>{message.content}</ReactMarkdown>
                    ) : (
                      <span className="typing">正在思考…</span>
                    )}
                  </div>
                  {message.content && (
                    <div className="message-actions">
                      <button
                        type="button"
                        onClick={() => {
                          void navigator.clipboard?.writeText(message.content);
                        }}
                      >
                        复制
                      </button>
                      <button
                        type="button"
                        onClick={() => void regenerate(message.id)}
                      >
                        重新生成
                      </button>
                    </div>
                  )}
                </>
              )}
              {message.role === "assistant" &&
                message.trace &&
                extractKlines(message.trace).length > 0 && (
                  <KlineChart candles={extractKlines(message.trace)} />
                )}
              {message.role === "assistant" &&
                message.trace &&
                extractScanResults(message.trace).length > 0 && (
                  <div className="scan-table-wrap">
                    <table className="scan-table">
                      <thead>
                        <tr>
                          <th>币种</th>
                          <th>最新价</th>
                          <th>24h 涨跌</th>
                          <th>成交额</th>
                          <th>信号</th>
                        </tr>
                      </thead>
                      <tbody>
                        {extractScanResults(message.trace).map((item) => (
                          <tr key={item.symbol}>
                            <td className="scan-symbol">{item.symbol}</td>
                            <td className="scan-num">
                              {Number(item.last_price).toLocaleString("en-US", {
                                maximumFractionDigits: 4,
                              })}
                            </td>
                            <td
                              className={`scan-num ${
                                item.price_change_percent_24h >= 0
                                  ? "scan-up"
                                  : "scan-down"
                              }`}
                            >
                              {item.price_change_percent_24h >= 0 ? "+" : ""}
                              {item.price_change_percent_24h.toFixed(2)}%
                            </td>
                            <td className="scan-num">
                              {item.quote_volume_24h >= 1e9
                                ? `${(item.quote_volume_24h / 1e9).toFixed(2)}B`
                                : item.quote_volume_24h >= 1e6
                                  ? `${(item.quote_volume_24h / 1e6).toFixed(1)}M`
                                  : item.quote_volume_24h.toFixed(0)}
                            </td>
                            <td className="scan-signals">
                              {item.signals.slice(0, 2).join(" · ") || "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              {message.role === "assistant" &&
                message.trace &&
                extractBacktestResult(message.trace) && (
                  <BacktestCard
                    result={extractBacktestResult(message.trace)!}
                  />
                )}
              {message.role === "assistant" &&
                message.trace &&
                extractPortfolioRisk(message.trace) && (
                  <PortfolioRiskCard
                    result={extractPortfolioRisk(message.trace)!}
                  />
                )}
              {message.role === "assistant" &&
                message.trace &&
                extractTradingPlans(message.trace).length > 0 &&
                extractTradingPlans(message.trace).map((plan, index) => (
                  <TradingPlanCard
                    key={`${plan.symbol}-${index}`}
                    plan={plan}
                  />
                ))}
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
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="询问行情、风险、回测，或委托一个监控任务…"
              rows={1}
            />
            <button
              className="mic-button"
              type="button"
              aria-label={listening ? "正在聆听" : "语音输入"}
              title="语音输入"
              onClick={startListening}
              disabled={isSending}
            >
              {listening ? "●" : "🎤"}
            </button>
            <button
              className="send-button"
              type="submit"
              aria-label={isSending ? "正在发送" : "发送消息"}
              disabled={!input.trim() || isSending}
            >
              {isSending ? "…" : "↑"}
            </button>
          </form>
          <p className="composer-hint">
            Enter 发送 · Shift+Enter 换行 · 首月不执行真实交易
          </p>
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
            <h4>市场行情</h4>
            {tickers.length === 0 ? (
              <p className="insight-empty">行情加载中…</p>
            ) : (
              <ul className="insight-list">
                {tickers.map((ticker) => (
                  <li key={ticker.symbol}>
                    <strong>{ticker.symbol.replace("USDT", "")}</strong>
                    <span className="ticker-price">
                      {Number(ticker.price).toLocaleString("en-US", {
                        maximumFractionDigits: 2,
                      })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

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
            <h4>工具调用</h4>
            {(() => {
              const usage = computeToolUsage(messages);
              const names = Object.keys(usage);
              return names.length === 0 ? (
                <p className="insight-empty">本次会话还没有调用工具。</p>
              ) : (
                <ul className="insight-list">
                  {names.map((name) => (
                    <li key={name}>
                      <strong>{name}</strong>
                      <span>{usage[name]} 次</span>
                    </li>
                  ))}
                </ul>
              );
            })()}
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

      {commandOpen && (
        <div className="command-overlay" onClick={() => setCommandOpen(false)}>
          <div
            className="command-palette"
            onClick={(event) => event.stopPropagation()}
          >
            <input
              className="command-input"
              autoFocus
              value={commandQuery}
              onChange={(event) => setCommandQuery(event.target.value)}
              placeholder="搜索命令…"
            />
            <ul className="command-list">
              {filteredCommands.map((command) => (
                <li key={command.id}>
                  <button
                    type="button"
                    onClick={() => {
                      command.run();
                      setCommandOpen(false);
                    }}
                  >
                    <span className="command-icon">{command.icon}</span>
                    {command.label}
                  </button>
                </li>
              ))}
              {filteredCommands.length === 0 && (
                <li className="command-empty">没有匹配的命令</li>
              )}
            </ul>
          </div>
        </div>
      )}
    </main>
  );
}

export default App;
