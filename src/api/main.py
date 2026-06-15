from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.routes import agent_types, apprentice
from src.infra.postgres_client import close_pool, init_pool, initialize_knowledge_schema


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool = await init_pool()
    await initialize_knowledge_schema(pool)
    yield
    await close_pool()


app = FastAPI(lifespan=lifespan, title="Agent Lifecycle Framework")
app.include_router(agent_types.router, prefix="/api/v1")
app.include_router(apprentice.router, prefix="/api/v1")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request,
    exc: RequestValidationError,
) -> JSONResponse:
    for error in exc.errors():
        if error.get("loc") == ("body", "topic_list"):
            return JSONResponse(
                status_code=400,
                content={"detail": "topic_list must not be empty"},
            )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})
