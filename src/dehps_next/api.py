import hmac
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout

from .artifacts import Artifacts
from .config import Settings
from .db import Database
from .errors import DomainError
from .status import get_status


def create_app(settings=None):
    settings = settings or Settings.from_env()
    if len(settings.api_token) < 24:
        raise ValueError("A private API token of at least 24 characters is required")

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = Database(settings)
        app.state.artifacts = Artifacts(settings, app.state.db)
        yield
        app.state.db.close()

    app = FastAPI(
        title="DEHPS Next read-only learning and research evidence API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def headers(request, call_next):
        request.state.request_id = str(uuid.uuid4())
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        logging.getLogger("dehps_next").info(
            json.dumps(
                {
                    "event": "request",
                    "path": request.url.path,
                    "request_id": request.state.request_id,
                    "status": response.status_code,
                    "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
                }
            )
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(
            status_code=409, content={"code": exc.code, "request_id": request.state.request_id}
        )

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        logging.getLogger("dehps_next").exception("Unhandled API error")
        return JSONResponse(
            status_code=500,
            content={"code": "INTERNAL_ERROR", "request_id": getattr(request.state, "request_id", None)},
        )

    def auth(authorization: str = Header(default="")):
        if not hmac.compare_digest(authorization, "Bearer " + settings.api_token):
            raise HTTPException(401, detail="Authentication required")

    @app.get("/health")
    def health():
        return {"status": "online", "version": "0.1.0"}

    @app.get("/ready")
    def ready(request: Request):
        try:
            if not request.app.state.db.rows("SELECT 1 FROM schema_migrations WHERE version=4"):
                return JSONResponse(status_code=503, content={"status": "not_ready"})
            return {"status": "ready"}
        except (DatabaseError, PoolTimeout):
            return JSONResponse(status_code=503, content={"status": "not_ready"})

    @app.get("/status", dependencies=[Depends(auth)])
    def status(request: Request):
        return jsonable_encoder(get_status(request.app.state.db, request.app.state.artifacts))

    @app.get("/evidence/{loop_id}", dependencies=[Depends(auth)])
    def evidence(loop_id: str, request: Request):
        if len(loop_id) > 80:
            raise HTTPException(422, detail="Invalid loop name")
        return request.app.state.db.rows(
            """SELECT cy.issue,cy.purpose,cy.state,cy.dataset_id,cy.parent_model_id,
            cy.model_id,p.mode,p.sealed_at,p.payload_digest,e.metrics,m.manifest
            FROM cycles cy LEFT JOIN predictions p ON p.cycle_id=cy.id
            LEFT JOIN evaluations e ON e.cycle_id=cy.id LEFT JOIN models m ON m.id=cy.model_id
            WHERE cy.loop_id=%s ORDER BY cy.draw_at DESC LIMIT 100""",
            (loop_id,),
        )

    @app.get("/research/{campaign_id}", dependencies=[Depends(auth)])
    def research(campaign_id: str, request: Request):
        if len(campaign_id) > 80:
            raise HTTPException(422, detail="Invalid campaign name")
        db = request.app.state.db
        return {
            "campaign": db.rows("SELECT * FROM research_campaigns WHERE id=%s", (campaign_id,)),
            "nodes": db.rows(
                "SELECT path,parent_id,spec,hypothesis,status,evaluation,decision FROM research_nodes WHERE campaign_id=%s ORDER BY created_at LIMIT 100",
                (campaign_id,),
            ),
            "decisions": db.rows(
                "SELECT * FROM research_decisions WHERE campaign_id=%s ORDER BY id LIMIT 200", (campaign_id,)
            ),
        }

    return app
