from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from cms.config import settings

_client: AsyncIOMotorClient | None = None


def reset_client() -> None:
    """Bağlantı hatası sonrası bir sonraki denemede yeni URI ile yeniden bağlan."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.mongo_db]


async def ensure_indexes() -> None:
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.pages.create_index("slug", unique=True)
    await db.pages.create_index("published")
    await db.ui_profiles.create_index("key", unique=True)
