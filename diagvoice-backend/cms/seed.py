"""Bootstrap admin user and default demo page + UI profile."""

import asyncio
import logging
from datetime import UTC, datetime

from cms.auth_utils import hash_password
from cms.config import settings
from cms.database import get_db, reset_client
from cms.serialize import normalize_slug

log = logging.getLogger("cms.seed")

DEFAULT_PROFILE_KEY = "default-demo"

DEFAULT_CARDS = [
    {"id": "transcript", "displayTitle": "Çevrilen Metin"},
    {"id": "audio_emotion", "displayTitle": "Ses Duygusu (Emosyon)"},
    {"id": "disease", "displayTitle": "WURSS"},
    {"id": "benchmark_v2", "displayTitle": "İş Sağlığı"},
    {"id": "mental_fitness", "displayTitle": "Mental Fitness"},
    {"id": "depression", "displayTitle": "Depresyon"},
    {"id": "sentiment", "displayTitle": "Analiz Sonucu"},
]


async def seed_admin_if_empty() -> None:
    """Koleksiyon adı MongoDB’de `users` (çoğul). Atlas / uzak DB gecikmesi için birkaç deneme."""
    email = settings.cms_admin_email.lower().strip()
    pwd = settings.cms_admin_password
    last_err: Exception | None = None
    for attempt in range(1, 11):
        try:
            db = get_db()
            count = await db.users.count_documents({})
            if count > 0:
                log.info("CMS users zaten var (%s kayıt), admin seed atlandı.", count)
                return
            await db.users.insert_one(
                {
                    "email": email,
                    "passwordHash": hash_password(pwd),
                    "role": "admin",
                    "createdAt": datetime.now(UTC),
                }
            )
            log.info("CMS admin kullanıcı oluşturuldu: %s (koleksiyon: users)", email)
            return
        except Exception as e:
            last_err = e
            log.warning("CMS admin seed denemesi %s/10 başarısız: %s", attempt, e)
            reset_client()
            await asyncio.sleep(1.5)
    if last_err:
        raise last_err


async def seed_default_demo_if_missing() -> None:
    db = get_db()
    now = datetime.now(UTC)

    prof = await db.ui_profiles.find_one({"key": DEFAULT_PROFILE_KEY})
    if not prof:
        await db.ui_profiles.insert_one(
            {
                "key": DEFAULT_PROFILE_KEY,
                "label": "Varsayılan demo",
                "cards": DEFAULT_CARDS,
                "updatedAt": now,
            }
        )
        log.info("CMS varsayılan ui_profile eklendi: %s", DEFAULT_PROFILE_KEY)

    slug = normalize_slug("/")
    page = await db.pages.find_one({"slug": slug})
    if not page:
        await db.pages.insert_one(
            {
                "slug": slug,
                "title": "DiagVoice Demo",
                "description": "Ses analizi özeti",
                "published": True,
                "sortOrder": 0,
                "profileKey": DEFAULT_PROFILE_KEY,
                "layout": "demo_default",
                "updatedAt": now,
            }
        )
        log.info("CMS varsayılan sayfa eklendi: slug=%s", slug)
