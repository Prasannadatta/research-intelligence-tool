from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.authors import router as authors_router
from app.api.routes.analysis import router as analysis_router
from app.api.routes.data_updater import router as data_updater_router
from app.api.routes.grants import router as grants_router
from app.api.routes.saved_searches import router as saved_searches_router
from app.api.routes.search import router as search_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.core.config import get_settings
    from app.db.session import init_db

    settings = get_settings()
    if settings.author_resolution_enabled:
        try:
            await init_db()
        except Exception:
            # Search still works without resolution if DB init fails.
            pass
    yield


app = FastAPI(
    title="Research Intelligence Tool API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(authors_router)
app.include_router(search_router)
app.include_router(analysis_router)
app.include_router(grants_router)
app.include_router(saved_searches_router)
app.include_router(data_updater_router)


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "message": "Backend is running",
    }
