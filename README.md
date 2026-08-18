# Trading Agent

面向 Crypto 交易研究的对话式 AI Agent。自研 Mini Harness(Agent Loop、工具注册、上下文管理、权限确认、评测集),30+ 个确定性工具,苹果风前端,已上线 Railway 可部署。

## 当前能力

- **苹果风界面**:毛玻璃材质、弹簧反馈、⌘K 命令面板、深浅色主题、PWA 手机适配。
- **真 token 级流式输出**(SSE),含 DeepSeek Reasoner 思考过程;消息支持 Markdown、复制/重新生成/反馈。
- **自研 Agent Loop**:模型判断、工具调用、结果观察、继续推理、最终回答。
- **30+ 工具统一注册**:参数校验、超时、权限分级(read/write/simulate)、统一错误。
- **Binance 多市场**:现货/U本位/币本位/期权报价与 K 线,全市场扫描,MA20/RSI/ATR/布林带/成交量。
- **技术分析**:支撑阻力、双顶双底形态识别;MA 突破信号回测与事件影响回测(带数据来源与限制说明)。
- **交易闭环**:持仓与风险分析、交易计划、模拟订单(人工确认)、复盘(自动计算多空盈亏)。
- **对话式监控**:价格提醒任务,后台轮询、冷却、飞书通知、暂停恢复。
- **RAG 知识库**:139 条交易大师心法 + 研究笔记,TF-IDF 检索;全网搜索(search_web)。
- **新闻与宏观**:可插拔消息源,未配置时明确降级、绝不伪造。
- **持久化**:PostgreSQL 保存会话/轨迹/持仓/计划/确认票据,支持重启恢复;长对话自动压缩(摘要游标)。
- **首月只读**:无真实下单/提现/转账,模拟订单需确认。

## 目录

```text
apps/web/                  React + TypeScript 前端
services/api/app/agent/    自研 Agent/Harness 核心（loop、tools、context、memory、权限、评测）
services/api/app/backtest/ 信号回测
services/api/app/patterns/ 技术形态识别与事件回测
services/api/app/monitoring/ 价格监控与提醒
services/api/app/portfolio/ 持仓与风险
services/api/app/trading/  交易计划、模拟订单与复盘
services/api/app/notes/    研究笔记与 RAG
services/api/app/rag/      交易知识库与向量检索
services/api/app/news/     新闻与宏观事件源
services/api/app/tools/    Binance 行情工具
services/api/tests/        后端行为测试
docs/                      架构、进度、Harness 对照、部署
```

## 架构

完整架构图、技术栈、核心设计(Agent Loop / 工具系统 / Context / 权限 / 数据流)见 [docs/architecture.md](docs/architecture.md)。

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
$env:DATABASE_URL="postgresql+asyncpg://trading:local-development-only@localhost:5432/trading"
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

## 部署

一键 Docker 部署(前端 + 后端 + PostgreSQL),国内云服务器步骤见 [docs/deployment.md](docs/deployment.md)。

```powershell
cp .env.example .env   # 填入 DEEPSEEK_API_KEY 和数据库密码
docker compose up -d --build
# 访问 http://服务器IP:8080
```
