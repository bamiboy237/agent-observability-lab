"""This script adds seed data for support operations to the configured database."""

import asyncio

from app.db import get_session_factory
from app.domain.support.seed import seed_support_data


async def main() -> None:
    async with get_session_factory().begin() as session:
        summary = await seed_support_data(session)
    print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
