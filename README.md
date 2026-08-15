# Lobster Trading Agent

一个以学习全栈开发和 Agent/Harness 工程为第一目标的交易辅助 Agent。

## 当前状态

项目处于 Day 0：开发基线。当前只提供可运行的前端入口、后端健康检查、数据库容器和测试环境。Day 1 的聊天界面由学习者按照 `docs/day-01.md` 亲手完成。

## 目录

```text
apps/web/       React + TypeScript 前端
services/api/   FastAPI 后端
docs/           路线、练习和进度
```

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
```

## 验证

```powershell
npm run test:web
cd services/api
uv run pytest
```

正式功能按照 `docs/roadmap.md` 分阶段实现。核心 Agent 代码由学习者亲手完成，重复配置和交易所适配可以使用 AI 辅助。

