import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from pymongo import AsyncMongoClient

from app.core.config import get_settings
from app.repositories.indexes import create_indexes
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.customer import router as customer_router

logger = logging.getLogger(__name__)



@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    client = AsyncMongoClient(settings.mongodb_uri)
    try:
        database = client[settings.mongodb_database]

        try:
            await database.command("ping")
        except Exception as exc:
            logger.error(
                "Failed to connect to MongoDB database '%s': %s",
                settings.mongodb_database,
                exc,
            )
            raise RuntimeError(
                f"Database connection verification failed: {exc}"
            ) from exc

        try:
            await create_indexes(database)
        except Exception as exc:
            logger.error("Failed to initialize MongoDB indexes: %s", exc)
            raise RuntimeError(
                f"Database index initialization failed: {exc}"
            ) from exc

        app.state.mongo_client = client
        app.state.database = database

        yield
    finally:
        await client.close()


app = FastAPI(
    title=get_settings().app_name,
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(customer_router)

from pathlib import Path

from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"
ADMIN_HTML = STATIC_DIR / "admin.html"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/login", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/app", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_frontend():
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return {"message": "WaveNxD AI Sales Representative API"}


@app.api_route("/admin", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/admin/", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_admin_portal():
    if ADMIN_HTML.exists():
        return FileResponse(str(ADMIN_HTML))
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return {"message": "WaveNxD Admin Portal"}


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
async def favicon():
    return Response(content=b"", media_type="image/x-icon")



@app.api_route("/health", methods=["GET", "HEAD"], tags=["Health"])
async def health():
    return {
        "status": "ok",
        "application": get_settings().app_name,
    }


@app.api_route("/health/db", methods=["GET", "HEAD"], tags=["Health"])
async def database_health(request: Request):
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise RuntimeError("Database client is not initialized")
    await database.command("ping")

    return {
        "status": "ok",
        "database": get_settings().mongodb_database,
    }

