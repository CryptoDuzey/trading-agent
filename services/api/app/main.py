from typing import Literal, TypedDict

from fastapi import FastAPI


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: Literal["lobster-api"]


app = FastAPI(title="Lobster Trading Agent API")


@app.get("/health")
async def health() -> HealthResponse:
    return {
        "status": "ok",
        "service": "lobster-api",
    }

