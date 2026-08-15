import "./styles.css";

function App() {
  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">30 天全栈与 Agent 工程训练</p>
        <h1>Lobster Trading Agent</h1>
        <p className="summary">
          当前是开发基线。页面没有提前放入聊天实现，因为那是你的第一项手写练习。
        </p>
      </header>

      <section className="next-step" aria-labelledby="next-step-title">
        <span className="day-label">NEXT</span>
        <div>
          <h2 id="next-step-title">Day 1：亲手完成对话界面</h2>
          <p>打开 docs/day-01.md，按照练习顺序完成消息、输入和异步回复。</p>
        </div>
      </section>
    </main>
  );
}

export default App;

