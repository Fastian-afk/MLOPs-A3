import hashlib
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent.config import Settings
from agent.orchestrator import Orchestrator
from agent.registry import ToolRegistry, build_registry
from agent.schemas import ChatRequest, ChatResponse

bearer = HTTPBearer(auto_error=False)


def create_app(settings: Settings | None = None, registry: ToolRegistry | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        app.state.orchestrator = Orchestrator(settings, registry or build_registry(settings))
        yield

    app = FastAPI(title="MLOps Evidence Agent", version="1.0.0", lifespan=lifespan)

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
        configured = settings.api_token.get_secret_value() if settings.api_token else ""
        if not configured:
            raise HTTPException(503, "Set MLOPS_API_TOKEN securely before using the agent")
        if not credentials or not secrets.compare_digest(credentials.credentials, configured):
            raise HTTPException(401, "Valid bearer authentication required")
        return hashlib.sha256(configured.encode()).hexdigest()[:24]

    @app.get("/health")
    def health():
        return {"status": "ok", "planner": settings.planner, "authentication_configured": bool(settings.api_token)}

    @app.post("/agent/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, user_id: Annotated[str, Depends(authenticate)]):
        return await app.state.orchestrator.chat(request, user_id)

    @app.get("/agent/tools")
    def tools(user_id: Annotated[str, Depends(authenticate)]):
        return [{"name": s.name, "purpose": s.description, "permission": s.permission, "timeout": s.timeout,
                 "input_schema": s.input_model.model_json_schema(), "output_schema": s.output_model.model_json_schema()}
                for s in app.state.orchestrator.registry.tools.values()]

    return app


app = create_app()
