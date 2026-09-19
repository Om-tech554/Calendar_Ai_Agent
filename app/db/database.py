"""
MongoDB connection management using Motor (async) and Beanie ODM.
"""

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _patch_motor_append_metadata() -> None:
    """
    Compatibility fix for Beanie 2.2+ with Motor 3.7+:
    PyMongo 4.14+ added append_metadata to MongoClient, but Motor's AsyncIOMotorClient
    does not directly wrap it, causing __getattr__ to return an AsyncIOMotorDatabase
    which raises a TypeError when Beanie attempts to call it.
    """
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        def _append_metadata(self, *args, **kwargs):
            if hasattr(self.delegate, "append_metadata"):
                return self.delegate.append_metadata(*args, **kwargs)
        AsyncIOMotorClient.append_metadata = _append_metadata


_patch_motor_append_metadata()

# Global MongoDB client (singleton)
_client: AsyncIOMotorClient | None = None  # type: ignore[type-arg]


async def connect_db() -> None:
    """
    Initialize MongoDB connection and Beanie ODM.
    Called during FastAPI lifespan startup.
    """
    global _client

    # Import models here to avoid circular imports
    from app.db.models import User, OAuthToken, ChatSession, ChatMessage

    logger.info("db_connecting", url=settings.MONGODB_URL[:30] + "...")

    client_kwargs: dict = {
        "serverSelectionTimeoutMS": 5000,
        "connectTimeoutMS": 5000,
        "maxPoolSize": 10,
        "minPoolSize": 1,
    }
    if "mongodb+srv" in settings.MONGODB_URL or "tls=true" in settings.MONGODB_URL.lower() or "ssl=true" in settings.MONGODB_URL.lower():
        try:
            import certifi
            client_kwargs["tlsCAFile"] = certifi.where()
        except ImportError:
            pass

    _client = AsyncIOMotorClient(
        settings.MONGODB_URL,
        **client_kwargs,
    )

    # Initialize Beanie with all document models
    await init_beanie(
        database=_client[settings.MONGODB_DB_NAME],
        document_models=[User, OAuthToken, ChatSession, ChatMessage],
    )

    # Verify connection
    await _client.admin.command("ping")
    logger.info("db_connected", db=settings.MONGODB_DB_NAME)


async def disconnect_db() -> None:
    """Close MongoDB connection. Called during FastAPI lifespan shutdown."""
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("db_disconnected")


async def ping_db() -> bool:
    """Health check — returns True if database is reachable."""
    try:
        if _client is None:
            return False
        await _client.admin.command("ping")
        return True
    except Exception:
        return False
