"""This module proves simulation never touches the configured database.

Simulated refund and ticket actions run against disposable in-memory state.
The orders and tickets tables of the configured database must not change
before, during, or after the simulation.
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import select, text

from app.config import Settings
from app.db import get_session_factory
from app.domain.simulation.scenarios import SCENARIO_BY_ID
from app.domain.simulation.stateful import StatefulSupportAdapter


@pytest.fixture(scope="module", autouse=True)
def apply_migrations() -> None:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for simulation integration tests")
    if settings.environment != "test" or os.environ.get("RUN_DATABASE_TESTS") != "1":
        pytest.skip("set ENVIRONMENT=test and RUN_DATABASE_TESTS=1 for an isolated database")
    command.upgrade(Config("alembic.ini"), "head")


@pytest.mark.integration
async def test_simulation_leaves_database_untouched() -> None:
    async with get_session_factory()() as session:
        orders_before = (
            await session.execute(
                select(text("id"), text("status")).select_from(text("orders")).order_by(text("id"))
            )
        ).all()
        tickets_before = await session.execute(
            select(text("count(*)")).select_from(text("tickets"))
        )
        ticket_count_before = tickets_before.scalar_one()

    state = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"].initial_state
    adapter = StatefulSupportAdapter(refund_confirmed=True)
    await adapter.seed(state)
    await adapter.call("get_order_status", {"order_id": state.orders[0].id})
    await adapter.call("propose_refund", {"order_id": state.orders[0].id})
    await adapter.call("confirm_refund", {"order_id": state.orders[0].id})
    await adapter.call("escalate", {"subject": "Escalated support request"})
    await adapter.reset()

    async with get_session_factory()() as session:
        orders_after = (
            await session.execute(
                select(text("id"), text("status")).select_from(text("orders")).order_by(text("id"))
            )
        ).all()
        tickets_after = await session.execute(select(text("count(*)")).select_from(text("tickets")))
        ticket_count_after = tickets_after.scalar_one()

    assert orders_before == orders_after
    assert ticket_count_before == ticket_count_after
    assert [row[1] for row in orders_before] == [row[1] for row in orders_after]
