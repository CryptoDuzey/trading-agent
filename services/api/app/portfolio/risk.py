from datetime import UTC, datetime
from decimal import Decimal

from app.portfolio.models import (
    PortfolioRisk,
    Position,
    PositionMark,
    PositionRisk,
    RiskFlag,
    RiskLevel,
)


def analyze_portfolio_risk(
    positions: list[Position],
    marks: dict[str, PositionMark],
    *,
    account_equity: Decimal | str | None = None,
    now: datetime | None = None,
    max_market_age_seconds: int = 60,
) -> PortfolioRisk:
    current_time = now or datetime.now(UTC)
    position_risks: list[PositionRisk] = []
    flags: list[RiskFlag] = []
    notionals: dict[str, Decimal] = {}
    total_pnl = Decimal(0)

    for position in positions:
        mark = marks.get(position.id)
        if mark is None:
            flags.append(
                RiskFlag(
                    code="missing_market_data",
                    level="critical",
                    position_id=position.id,
                    message=f"{position.symbol} 缺少当前价格，无法计算持仓风险。",
                )
            )
            continue
        age_seconds = (current_time - mark.observed_at).total_seconds()
        if age_seconds > max_market_age_seconds:
            flags.append(
                RiskFlag(
                    code="stale_market_data",
                    level="critical",
                    position_id=position.id,
                    message=f"{position.symbol} 行情已过期，拒绝计算实时风险。",
                )
            )
            continue

        notional = position.quantity * mark.price
        direction = Decimal(1) if position.side == "long" else Decimal(-1)
        pnl = (mark.price - position.entry_price) * position.quantity * direction
        initial_margin = (
            position.quantity * position.entry_price / position.leverage
        )
        return_on_margin = (
            pnl / initial_margin * Decimal(100)
            if initial_margin > 0
            else Decimal(0)
        )
        stop_distance: Decimal | None = None
        if position.stop_loss is None:
            flags.append(
                RiskFlag(
                    code="missing_stop",
                    level="medium",
                    position_id=position.id,
                    message=f"{position.symbol} 未设置止损参考价。",
                )
            )
        else:
            stop_distance = (
                (mark.price - position.stop_loss) / mark.price * Decimal(100)
                if position.side == "long"
                else (position.stop_loss - mark.price) / mark.price * Decimal(100)
            )
            if stop_distance <= 0:
                flags.append(
                    RiskFlag(
                        code="stop_crossed",
                        level="critical",
                        position_id=position.id,
                        message=f"{position.symbol} 当前价格已经越过止损参考价。",
                    )
                )
        if position.leverage >= 10:
            flags.append(
                RiskFlag(
                    code="high_leverage",
                    level="high",
                    position_id=position.id,
                    message=f"{position.symbol} 使用 {position.leverage} 倍杠杆。",
                )
            )

        notionals[position.id] = notional
        total_pnl += pnl
        position_risks.append(
            PositionRisk(
                position_id=position.id,
                market=position.market,
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
                mark_price=mark.price,
                notional=_number(notional),
                unrealized_pnl=_number(pnl),
                return_on_margin_percent=_number(return_on_margin),
                stop_distance_percent=(
                    _number(stop_distance) if stop_distance is not None else None
                ),
            )
        )

    total_notional = sum(notionals.values(), Decimal(0))
    largest_percent: Decimal | None = None
    if total_notional > 0:
        largest_position_id, largest_notional = max(
            notionals.items(), key=lambda item: item[1]
        )
        largest_percent = largest_notional / total_notional * Decimal(100)
        if largest_percent >= 50 and len(notionals) > 1:
            largest_position = next(
                position for position in positions if position.id == largest_position_id
            )
            flags.append(
                RiskFlag(
                    code="concentration",
                    level="high",
                    position_id=largest_position_id,
                    message=(
                        f"{largest_position.symbol} 占组合名义敞口 "
                        f"{_number(largest_percent)}%。"
                    ),
                )
            )

    equity = Decimal(str(account_equity)) if account_equity is not None else None
    gross_leverage = total_notional / equity if equity and equity > 0 else None
    if gross_leverage is not None and gross_leverage >= 3:
        flags.append(
            RiskFlag(
                code="high_gross_leverage",
                level="high",
                message=f"组合总名义敞口为账户权益的 {_number(gross_leverage)} 倍。",
            )
        )

    risk_level = _risk_level(flags, has_positions=bool(position_risks))
    return PortfolioRisk(
        positions=position_risks,
        total_notional=_number(total_notional),
        total_unrealized_pnl=_number(total_pnl),
        gross_leverage=_number(gross_leverage) if gross_leverage is not None else None,
        largest_position_percent=(
            _number(largest_percent) if largest_percent is not None else None
        ),
        risk_level=risk_level,
        flags=flags,
        observed_at=current_time,
    )


def _number(value: Decimal) -> float:
    return float(round(value, 8))


def _risk_level(flags: list[RiskFlag], *, has_positions: bool) -> RiskLevel:
    if any(flag.level == "critical" for flag in flags):
        return "critical" if has_positions else "unknown"
    if any(flag.level == "high" for flag in flags):
        return "high"
    if any(flag.level == "medium" for flag in flags):
        return "medium"
    return "low" if has_positions else "unknown"
