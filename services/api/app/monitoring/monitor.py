import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import httpx
from pydantic import BaseModel

from app.monitoring.models import AlertObservation, AlertTask, AlertTrigger
from app.monitoring.rules import evaluate_alert
from app.monitoring.store import InMemoryAlertStore, PostgresAlertStore
from app.tools.binance_market import BinanceMarketClient, GetQuoteInput, MarketQuote

AlertStore = InMemoryAlertStore | PostgresAlertStore


class MarketClient(Protocol):
    async def get_quote(self, request: GetQuoteInput) -> MarketQuote: ...


class Notifier(Protocol):
    async def send(self, task: AlertTask, trigger: AlertTrigger) -> None: ...


class MonitorBatchResult(BaseModel):
    checked: int = 0
    triggered: int = 0
    notified: int = 0
    errors: int = 0


class FeishuNotifier:
    def __init__(
        self,
        webhook_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        if not webhook_url.startswith("https://"):
            raise ValueError("Feishu webhook URL must use HTTPS")
        self.webhook_url = webhook_url
        self.client = client
        self.timeout_seconds = timeout_seconds

    async def send(self, task: AlertTask, trigger: AlertTrigger) -> None:
        client = self.client or httpx.AsyncClient()
        owns_client = self.client is None
        text = (
            "Lobster 交易提醒\n"
            f"市场：{task.market}\n"
            f"标的：{task.symbol}\n"
            f"原因：{trigger.reason}\n"
            f"观测时间：{trigger.observation.observed_at.isoformat()}\n"
            "仅为条件提醒，不构成交易建议。"
        )
        try:
            response = await client.post(
                self.webhook_url,
                json={"msg_type": "text", "content": {"text": text}},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            code = payload.get("code", payload.get("StatusCode", 0))
            if code != 0:
                raise RuntimeError(f"Feishu rejected notification: {payload}")
        finally:
            if owns_client:
                await client.aclose()


class ChannelNotifier:
    def __init__(self, feishu: FeishuNotifier | None = None) -> None:
        self.feishu = feishu

    async def send(self, task: AlertTask, trigger: AlertTrigger) -> None:
        if task.notification_channel == "site":
            return
        if self.feishu is None:
            raise RuntimeError("FEISHU_WEBHOOK_URL is not configured")
        await self.feishu.send(task, trigger)


class AlertMonitor:
    def __init__(
        self,
        *,
        store: AlertStore,
        market_client: MarketClient | None = None,
        notifier: Notifier | None = None,
        batch_size: int = 100,
    ) -> None:
        self.store = store
        self.market_client = market_client or BinanceMarketClient()
        self.notifier = notifier or ChannelNotifier()
        self.batch_size = batch_size
        self._run_lock = asyncio.Lock()

    async def run_once(self, now: datetime | None = None) -> MonitorBatchResult:
        result = MonitorBatchResult()
        async with self._run_lock:
            tasks = await self.store.list_due(
                now or datetime.now(UTC),
                limit=self.batch_size,
            )
            for task in tasks:
                result.checked += 1
                try:
                    quote = await self.market_client.get_quote(
                        GetQuoteInput(market=task.market, symbol=task.symbol)
                    )
                    evaluation = evaluate_alert(
                        task,
                        AlertObservation(
                            price=Decimal(quote.price),
                            observed_at=quote.observed_at,
                        ),
                    )
                    trigger = await self.store.record_evaluation(task.id, evaluation)
                except Exception as error:  # noqa: BLE001 - monitoring boundary
                    await self.store.record_error(task.id, str(error))
                    result.errors += 1
                    continue

                if trigger is None:
                    continue
                result.triggered += 1
                try:
                    await self.notifier.send(task, trigger)
                except Exception as error:  # noqa: BLE001 - notification boundary
                    await self.store.mark_trigger_notification(
                        trigger.id,
                        notified=False,
                        error=str(error),
                    )
                    result.errors += 1
                else:
                    await self.store.mark_trigger_notification(
                        trigger.id,
                        notified=True,
                    )
                    result.notified += 1
        return result

    async def run_forever(
        self,
        stop_event: asyncio.Event,
        *,
        poll_seconds: float = 5,
    ) -> None:
        while not stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            except TimeoutError:
                continue
