from app.portfolio.models import Position, PositionMark
from app.portfolio.risk import analyze_portfolio_risk


def test_long_and_short_unrealized_pnl_are_calculated_from_mark_price() -> None:
    positions = [
        Position(
            id="long-btc",
            owner_id="owner",
            market="usdm",
            symbol="BTCUSDT",
            side="long",
            quantity="0.1",
            entry_price="60000",
            leverage="2",
            stop_loss="57000",
        ),
        Position(
            id="short-eth",
            owner_id="owner",
            market="usdm",
            symbol="ETHUSDT",
            side="short",
            quantity="1",
            entry_price="4000",
            leverage="4",
            stop_loss="4200",
        ),
    ]
    marks = {
        "long-btc": PositionMark(price="63000"),
        "short-eth": PositionMark(price="3800"),
    }

    result = analyze_portfolio_risk(positions, marks, account_equity="5000")

    assert result.positions[0].unrealized_pnl == 300
    assert result.positions[0].return_on_margin_percent == 10
    assert result.positions[1].unrealized_pnl == 200
    assert result.positions[1].return_on_margin_percent == 20
    assert result.total_unrealized_pnl == 500
    assert result.gross_leverage == 2.02


def test_portfolio_risk_flags_concentration_high_leverage_and_missing_stop() -> None:
    positions = [
        Position(
            id="large",
            owner_id="owner",
            market="usdm",
            symbol="BTCUSDT",
            side="long",
            quantity="1",
            entry_price="60000",
            leverage="20",
        ),
        Position(
            id="small",
            owner_id="owner",
            market="spot",
            symbol="ETHUSDT",
            side="long",
            quantity="1",
            entry_price="4000",
            leverage="1",
            stop_loss="3500",
        ),
    ]
    marks = {
        "large": PositionMark(price="60000"),
        "small": PositionMark(price="4000"),
    }

    result = analyze_portfolio_risk(positions, marks, account_equity="10000")

    assert result.largest_position_percent == 93.75
    assert result.risk_level == "high"
    assert {flag.code for flag in result.flags} >= {
        "missing_stop",
        "high_leverage",
        "concentration",
        "high_gross_leverage",
    }


def test_crossed_stop_is_reported_as_critical() -> None:
    position = Position(
        id="stopped",
        owner_id="owner",
        market="usdm",
        symbol="BTCUSDT",
        side="long",
        quantity="0.1",
        entry_price="60000",
        leverage="3",
        stop_loss="57000",
    )

    result = analyze_portfolio_risk(
        [position],
        {"stopped": PositionMark(price="56000")},
    )

    assert result.risk_level == "critical"
    assert result.positions[0].stop_distance_percent == -1.78571429
    assert any(flag.code == "stop_crossed" for flag in result.flags)


def test_risk_analysis_refuses_missing_or_stale_marks() -> None:
    position = Position(
        id="missing",
        owner_id="owner",
        market="spot",
        symbol="BTCUSDT",
        side="long",
        quantity="0.1",
        entry_price="60000",
    )

    result = analyze_portfolio_risk([position], {})

    assert result.positions == []
    assert result.risk_level == "unknown"
    assert result.flags[0].code == "missing_market_data"
