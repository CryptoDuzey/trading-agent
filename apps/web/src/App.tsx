import { FormEvent, useState } from "react";

import "./styles.css";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type StreamEvent = {
  content?: string;
};

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
      "我是 Lobster。你可以让我查询行情、分析风险或创建监控任务。当前版本只提供分析，不会执行真实交易。",
  },
];

async function readEventStream(
  response: Response,
  onDelta: (content: string) => void,
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
      const dataLine = block
        .split("\n")
        .find((line) => line.startsWith("data: "));
      if (!dataLine) continue;

      const event = JSON.parse(dataLine.slice(6)) as StreamEvent;
      if (event.content) onDelta(event.content);
    }

    if (done) break;
  }
}

function App() {
  const [sessionId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, session_id: sessionId }),
      });

      await readEventStream(response, (content) => {
        setMessages((current) =>
          current.map((item) =>
            item.id === assistantId
              ? { ...item, content: item.content + content }
              : item,
          ),
        );
      });
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
    <main className="workspace">
      <aside className="context-panel">
        <div className="brand-mark" aria-hidden="true">
          L
        </div>
        <div>
          <p className="overline">PRIVATE TRADING DESK</p>
          <h1>Lobster</h1>
        </div>

        <section className="market-status" aria-label="系统状态">
          <div className="status-heading">
            <span className="live-dot" />
            <span>分析服务在线</span>
          </div>
          <p>Binance · 只读模式</p>
        </section>

        <div className="context-copy">
          <span>当前工作区</span>
          <strong>新交易研究</strong>
          <p>尚未载入持仓和监控任务</p>
        </div>

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
          <button className="icon-button" type="button" aria-label="打开任务面板">
            任务 <span>0</span>
          </button>
        </header>

        <div className="message-list" aria-live="polite">
          {messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>
              <span className="message-role">
                {message.role === "assistant" ? "LOBSTER" : "YOU"}
              </span>
              <div className="message-content">
                {message.content || <span className="typing">正在思考…</span>}
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
              placeholder="询问行情、风险，或委托一个监控任务…"
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
    </main>
  );
}

export default App;
