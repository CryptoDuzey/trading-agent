# Lobster Trading Agent

面向 Crypto 交易研究的对话式 Agent。当前版本已经具备自研 Mini Harness、DeepSeek V4 模型适配、工具注册与执行、短期会话记忆、运行事件流，以及 Binance 多市场公开行情工具。

## 当前能力

- React 对话界面，支持桌面和手机，并可展开查看 Agent 的执行过程。
- FastAPI SSE 流式通信。
- Agent Loop：模型判断、工具调用、结果观察、继续推理、最终回答。
- DeepSeek `deepseek-v4-flash`，可通过环境变量切换模型。
- 工具参数校验、超时、统一错误和最大循环步数。
- Binance 现货、U 本位、币本位和期权的统一报价/K 线接口。
- Binance 全市场异常扫描，以及 MA20、RSI、ATR、布林带和成交量比率分析。
- PostgreSQL 保存对话、执行轨迹、确认票据和任务恢复点。
- 对话式价格监控任务，支持暂停、恢复、冷却、站内状态和飞书机器人通知。
- 首月只读：没有真实下单、提现或转账工具。

## 目录

```text
apps/web/                 React + TypeScript 前端
services/api/app/agent/   自研 Agent/Harness 核心
services/api/app/tools/   Agent 可调用的外部工具
services/api/tests/       后端行为测试
docs/                     路线和进度
```

## 配置

复制 `.env.example` 中需要的变量。不要把真实密钥提交到 Git。

```text
DEEPSEEK_API_KEY=your-key
DEEPSEEK_MODEL=deepseek-v4-flash
ENABLE_ALERT_MONITOR=true
ALERT_POLL_SECONDS=5
FEISHU_WEBHOOK_URL=可选的飞书机器人地址
```

没有配置密钥时系统仍可启动，但会明确提示模型未配置，不会伪造行情分析。

## 启动

前端：

```powershell
npm install
npm run dev:web
```

后端：

```powershell
cd services/api
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

数据库：

```powershell
docker compose up -d postgres
cd services/api
$env:DATABASE_URL="postgresql+asyncpg://lobster:local-development-only@localhost:5432/lobster"
uv run alembic upgrade head
```

没有设置 `DATABASE_URL` 时会自动使用内存模式，适合快速试用；正式使用时应配置数据库，以便服务重启后恢复历史、待确认任务和监控任务。飞书地址留空时，站内提醒仍然可用。

## 验证

```powershell
npm run test:web
npm run build:web
cd services/api
uv run pytest
$env:TEST_DATABASE_URL=$env:DATABASE_URL
uv run pytest tests/persistence/test_postgres_stores.py
```

Binance 衍生品接口可能根据服务器所在地区返回 HTTP 451。系统会把它记录为明确的工具错误，不会绕过地区限制或把失败解释成“没有行情”。
