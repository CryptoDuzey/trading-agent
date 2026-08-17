import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from app.monitoring.models import AlertObservation, CreateAlertInput
from app.monitoring.monitor import AlertMonitor, FeishuNotifier
from app.monitoring.rules import evaluate_alert
from app.monitoring.store import InMemoryAlertStore
from app.tools.binance_market import MarketQuote


class FixedQuoteClient:
    def __init__(self, price: str) -> None:
        self.price = price
        self.calls = 0

    async def get_quote(self, request):
        self.calls += 1
        return MarketQuote(
            market=request.market,
            symbol=request.symbol,
            price=self.price,
            observed_at=datetime.now(UTC),
        )


class RecordingNotifier:
    def __init__(self, *, error: str | None = None) -> None:
        self.error = error
        self.reasons: list[str] = []

    async def send(self, task, trigger) -> None:
        if self.error:
            raise RuntimeError(self.error)
        self.reasons.append(trigger.reason)


def test_one_shot_monitor_triggers_notifies_and_does_not_run_twice() -> None:
    async def exercise_monitor():
        store = InMemoryAlertStore()
        await store.create(
            "owner-a",
            CreateAlertInput(
                market="spot",
                symbol="BTCUSDT",
                condition="price_below",
                threshold="65000",
                one_shot=True,
            ),
        )
        quotes = FixedQuoteClient("64900")
        notifier = RecordingNotifier()
        monitor = AlertMonitor(store=store, market_client=quotes, notifier=notifier)

        first = await monitor.run_once()
        second = await monitor.run_once()
        tasks = await store.list_for_owner("owner-a")
        triggers = await store.list_triggers("owner-a")
        return first, second, tasks, triggers, quotes, notifier

    first, second, tasks, triggers, quotes, notifier = asyncio.run(exercise_monitor())

    assert first.checked == 1
    assert first.triggered == 1
    assert first.notified == 1
    assert second.checked == 0
    assert quotes.calls == 1
    assert notifier.reasons == ["BTCUSDT 价格 64900 已低于或等于 65000"]
    assert tasks[0].status == "completed"
    assert triggers[0].notified is True


def test_notification_failure_is_recorded_without_losing_trigger() -> None:
    async def exercise_monitor():
        store = InMemoryAlertStore()
        await store.create(
            "owner-a",
            CreateAlertInput(
                market="spot",
                symbol="ETHUSDT",
                condition="price_above",
                threshold="4000",
            ),
        )
        monitor = AlertMonitor(
            store=store,
            market_client=FixedQuoteClient("4100"),
            notifier=RecordingNotifier(error="Feishu unavailable"),
        )
        result = await monitor.run_once()
        return result, await store.list_triggers("owner-a")

    result, triggers = asyncio.run(exercise_monitor())

    assert result.triggered == 1
    assert result.notified == 0
    assert result.errors == 1
    assert triggers[0].notified is False
    assert triggers[0].notification_error == "Feishu unavailable"


def test_feishu_notifier_posts_a_readable_alert_message() -> None:
    requests: list[httpx.Request] = []

    async def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0})

    async def notify():
        store = InMemoryAlertStore()
        task = await store.create(
            "owner-a",
            CreateAlertInput(
                market="spot",
                symbol="BTCUSDT",
                condition="price_below",
                threshold="65000",
                notification_channel="feishu",
            ),
        )
        trigger = await store.record_evaluation(
            task.id,
            evaluate_alert(task, AlertObservation(price="64900")),
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle_request)
        ) as client:
            notifier = FeishuNotifier(
                "https://open.feishu.cn/open-apis/bot/v2/hook/test",
                client=client,
            )
            await notifier.send(task, trigger)

    asyncio.run(notify())

    assert len(requests) == 1
    body = requests[0].content.decode("utf-8")
    assert "Trading Agent 交易提醒" in body
    assert "BTCUSDT" in body
    assert "64900" in body


def test_application_lifespan_starts_and_stops_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module

    class LifecycleMonitor:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        async def run_forever(self, stop_event, *, poll_seconds: float = 5) -> None:
            self.started = True
            await stop_event.wait()
            self.stopped = True

    async def exercise_lifespan():
        monitor = LifecycleMonitor()
        monkeypatch.setattr(main_module, "alert_monitor", monitor)
        monkeypatch.setenv("ENABLE_ALERT_MONITOR", "true")
        async with main_module.lifespan(main_module.app):
            await asyncio.sleep(0)
            assert monitor.started is True
        return monitor

    monitor = asyncio.run(exercise_lifespan())

    assert monitor.stopped is True
