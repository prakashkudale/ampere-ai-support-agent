from contextlib import asynccontextmanager
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .model import ClaudeModel, ModelFailure
from .schemas import ChatRequest, ChatResponse
from .service import RequestConflict, SupportService
from .storage import Store


def create_app(settings=None, model=None):
    settings = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(api):
        api.state.service = SupportService(Store(settings.database_path), model or ClaudeModel(settings), settings)
        yield

    api = FastAPI(title="Ampere Support Agent", version="0.1.0", lifespan=lifespan)
    static_dir = Path(__file__).resolve().parent / "static"
    api.mount("/static", StaticFiles(directory=static_dir), name="static")

    @api.get("/", include_in_schema=False)
    def chat_page():
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    @api.middleware("http")
    async def limit_body(request: Request, call_next):
        if request.url.path == "/chat":
            # Read bounded chunks rather than relying on a client-supplied Content-Length.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 32_768:
                    return JSONResponse(status_code=413, content={"detail": "Request body too large"})
            request._body = bytes(body)
        return await call_next(request)

    @api.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Default errors echo invalid input; omit it to avoid leaking credentials.
        return JSONResponse(status_code=422, content={"detail": [
            {"location": list(error["loc"]), "type": error["type"]} for error in exc.errors()]})

    @api.get("/health")
    def health():
        return {"status": "ok", "discord_mode": "mock"}

    @api.post("/chat", response_model=ChatResponse)
    def chat(body: ChatRequest, request: Request):
        try:
            return request.app.state.service.chat(body)
        except RequestConflict:
            raise HTTPException(409, "Request ID was already used with different content") from None
        except ModelFailure:
            raise HTTPException(503, "The AI provider is unavailable or returned an invalid response. Retry later using the same request ID.") from None
        except sqlite3.Error:
            raise HTTPException(503, "Storage is temporarily unavailable. Retry later using the same request ID.") from None

    return api


app = create_app()
