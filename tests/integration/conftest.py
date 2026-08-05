from collections.abc import AsyncGenerator

import pytest

from app.db import get_engine, get_session_factory


@pytest.fixture(autouse=True)
async def dispose_cached_engine() -> AsyncGenerator[None, None]:
    """This fixture keeps asynchronous connections from the pool in the event loop
    that creates them.
    """
    yield
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()
