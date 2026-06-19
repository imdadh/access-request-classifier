import logging
import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db.models import Base
from app.db.seed import seed_database
from app.db.session import engine, SessionLocal
from app.routers import access_requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure template and static directories exist
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "ui", "templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "ui", "static")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

templates = Jinja2Templates(directory=TEMPLATES_DIR)


def create_tables() -> None:
    """Create all database tables defined by the ORM models."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created.")


def perform_seed() -> None:
    """Load seed data into the database."""
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()


app = FastAPI(
    title="Access Request Classifier",
    description="AI-Powered Access Request Classification and Routing",
    version="0.1.0",
)

# Mount static files for CSS/JS
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(access_requests.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Return a clear JSON error response for malformed input."""
    return JSONResponse(
        status_code=422,
        content={
            "error": "Invalid request input",
            "detail": exc.errors(),
        },
    )


@app.on_event("startup")
def on_startup() -> None:
    """Initialize database schema and seed data on application startup."""
    logger.info("Starting up...")
    create_tables()
    perform_seed()
    logger.info("Startup complete.")


@app.on_event("shutdown")
def on_shutdown() -> None:
    """Dispose of the database engine connection pool on shutdown."""
    logger.info("Shutting down...")
    engine.dispose()
    logger.info("Shutdown complete.")
