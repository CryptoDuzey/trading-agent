from app.monitoring.models import (
    AlertEvaluation,
    AlertObservation,
    AlertTask,
    CreateAlertInput,
)


def evaluate_alert(
    task: CreateAlertInput | AlertTask,
    observation: AlertObservation,
) -> AlertEvaluation:
    if task.condition == "price_above":
        triggered = observation.price >= task.threshold
        relation = "高于或等于"
    else:
        triggered = observation.price <= task.threshold
        relation = "低于或等于"

    reason = (
        f"{task.symbol} 价格 {observation.price} 已{relation} {task.threshold}"
        if triggered
        else f"{task.symbol} 当前价格尚未达到提醒条件"
    )
    return AlertEvaluation(
        triggered=triggered,
        reason=reason,
        observation=observation,
    )
