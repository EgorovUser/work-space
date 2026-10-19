from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.core import auth, files
from app.core.auth import require_user
from app.core.config import ROOT, prepare
from app.core.db import init_db
from app.core.logging import apply_settings, bootstrap, log_scope, logger
from app.core.middleware import RequestContextMiddleware
from app.core.models import User
from app.core.registry import ModuleDisabled, snapshot, try_register
from app.core.setting_defs import CORE_DEFS
from app.core.settings_api import router as settings_router
from app.core.settings_store import get_int, get_str, register_defs, sync_definitions
from app.modules import setup_modules
from app.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.outbox import stop as stop_outbox
    from app.core.scheduler import stop as stop_scheduler

    with log_scope("core", "startup"):
        for name, setup in _core_setups():
            try_register(name, setup)
        logger.info("application ready")
    yield
    with log_scope("core", "shutdown"):
        stop_scheduler()
        stop_outbox()
        logger.info("application stopped")


def create_app() -> FastAPI:
    cfg = prepare()
    bootstrap()
    init_db()
    register_defs(CORE_DEFS)
    sync_definitions()
    apply_settings()
    seed()

    app = FastAPI(title=get_str("core", "ui.app_title"), lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.secret_key,
        session_cookie="session",
        max_age=get_int("core", "auth.session_max_age_hours") * 3600,
        same_site="lax",
        https_only=False,
    )
    app.include_router(auth.router)
    app.include_router(settings_router)
    app.include_router(files.router)
    app.add_api_route("/healthz", healthz, methods=["GET"])
    app.add_api_route("/api/system/check", system_check, methods=["POST"])
    app.add_api_route("/api/system/db", system_db, methods=["GET"])
    app.add_api_route("/api/system/db/check", system_db_check, methods=["POST"])
    app.add_api_route("/api/system/db/checkpoint", system_db_checkpoint, methods=["POST"])
    app.add_api_route("/api/system/db/vacuum", system_db_vacuum, methods=["POST"])
    setup_modules(app)

    @app.exception_handler(ModuleDisabled)
    async def module_disabled(_request, exc: ModuleDisabled):
        return JSONResponse(
            status_code=503,
            content={"detail": "Модуль недоступен", "module": exc.module},
        )

    @app.exception_handler(Exception)
    async def unhandled(_request, exc: Exception):
        if isinstance(exc, HTTPException):
            raise exc
        with log_scope("core", "http.unhandled"):
            logger.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка"})

    _mount_frontend(app)
    return app


def healthz() -> dict:
    from app.core.outbox import stats
    from app.core.scheduler import job_names

    modules = snapshot()
    overall = "ok" if modules and all(item["status"] == "ok" for item in modules.values()) else "degraded"
    outbox_stats = {"pending": None, "failed": None}
    try:
        outbox_stats = stats()
    except Exception:
        with log_scope("outbox", "stats"):
            logger.exception("outbox stats failed")
    return {
        "status": overall,
        "modules": modules,
        "jobs": job_names(),
        "outbox": outbox_stats,
    }


def system_check(user: User = Depends(require_user)) -> dict:
    from app.core.status_check import run_checks

    return run_checks(user.id)


def system_db(user: User = Depends(require_user)) -> dict:
    from app.core.db import db_info

    return db_info()


def system_db_check(user: User = Depends(require_user)) -> dict:
    from app.core.db import db_info, integrity_check

    try:
        detail = integrity_check()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Проверка не прошла") from exc
    payload = db_info()
    payload["detail"] = detail
    return payload


def system_db_checkpoint(user: User = Depends(require_user)) -> dict:
    from app.core.db import checkpoint

    try:
        payload = checkpoint()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Контрольная точка не записалась") from exc
    payload["detail"] = "Журнал записан в базу"
    return payload


def system_db_vacuum(user: User = Depends(require_user)) -> dict:
    from app.core.db import vacuum

    try:
        payload = vacuum()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Сжать базу не удалось") from exc
    payload["detail"] = "База сжата"
    return payload


def _core_setups():
    from app.core import files as files_module
    from app.core.auth import healthcheck as auth_health
    from app.core.db import healthcheck as db_health
    from app.core.outbox import setup as outbox_setup
    from app.core.scheduler import setup as scheduler_setup
    from app.core.settings_store import healthcheck as settings_health

    return (
        ("db", db_health),
        ("auth", auth_health),
        ("settings", settings_health),
        ("files", files_module.healthcheck),
        ("outbox", outbox_setup),
        ("scheduler", scheduler_setup),
    )


def _mount_frontend(app: FastAPI) -> None:
    dist = ROOT / "frontend" / "dist"
    index = dist / "index.html"
    if not index.is_file():
        return

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/") or full_path == "healthz":
            raise HTTPException(status_code=404, detail="Не найдено")
        root = dist.resolve()
        candidate = (dist / full_path).resolve() if full_path else index
        if not str(candidate).startswith(str(root)):
            raise HTTPException(status_code=404, detail="Не найдено")
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
