import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.db import get_session_factory
from app.domain.support.models import Order
from app.domain.support.seed import ORDERS, seed_support_data


@pytest.fixture(scope="module", autouse=True)
def apply_seed_migration() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for seed integration tests")
    command.upgrade(Config("alembic.ini"), "head")


@pytest.mark.integration
async def test_seed_is_deterministic_and_preserves_existing_order_state() -> None:
    async with get_session_factory().begin() as session:
        first = await seed_support_data(session)

        mutable_order_id = ORDERS[0]["id"]
        mutable_order = await session.scalar(select(Order).where(Order.id == mutable_order_id))
        assert mutable_order is not None
        mutable_order.status = "processing"
        await session.flush()

        second = await seed_support_data(session)

        assert second == first
        assert second.customer_count == 2
        assert second.order_count == 6
        assert second.policy_document_count == 1
        assert len(second.policy_content_hashes[0]) == 64
        assert mutable_order.status == "processing"

        await session.rollback()
