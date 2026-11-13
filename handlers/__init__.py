from aiogram import Router

from .osint import router as osint_router
from .start import router as start_router
from .profile import router as profile_router
from .subscriptions import router as subscriptions_router


def get_combined_router() -> Router:
    main_router = Router()

    main_router.include_router(osint_router)
    main_router.include_router(start_router)
    main_router.include_router(profile_router)
    main_router.include_router(subscriptions_router)

    return main_router