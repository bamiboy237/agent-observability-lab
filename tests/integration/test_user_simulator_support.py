"""Integration checks for the persona simulator's real support sandbox."""


import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import func, select

from app.config import Settings
from app.db import get_session_factory
from app.domain.simulation.postgres import PostgresSandboxTarget, PostgresSupportSandbox
from app.domain.simulation.scenarios import SCENARIO_BY_ID
from app.domain.support.models import Order, Ticket


@pytest.fixture(scope="module", autouse=True)
def apply_migrations() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for simulation integration tests")
    command.upgrade(Config("alembic.ini"), "head")


async def _snapshot() -> tuple[list[tuple[object, object]], int]:
    async with get_session_factory()() as session:
        orders = (
            await session.execute(select(Order.id, Order.status).order_by(Order.id))
        ).all()
        tickets = await session.scalar(select(func.count()).select_from(Ticket))
    return list(orders), tickets or 0


@pytest.mark.integration
async def test_support_adapter_seeds_observes_failure_and_success_then_rolls_back() -> None:
    before = await _snapshot()
    source = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]
    scenario = source.model_copy(
        update={
            "request": source.request.model_copy(update={"refund_confirmed": True}),
            "content_hash": None,
        }
    )
    settings = Settings()  # type: ignore[call-arg]
    target = PostgresSandboxTarget.from_database_url(
        str(settings.database_url), environment=settings.environment
    )
    order_id = source.initial_state.orders[0].id

    async with get_session_factory()() as session:
        transaction = await session.begin()
        try:
            sandbox = PostgresSupportSandbox(
                session, scenario, isolation_confirmed=True, target=target
            )
            await sandbox.seed(scenario.initial_state)

            failed = await sandbox.call("confirm_refund", {"order_id": order_id})
            observed = await sandbox.call("get_order_status", {"order_id": order_id})
            proposed = await sandbox.call(
                "propose_refund",
                {"order_id": order_id, "reason": "Customer requested a refund"},
            )
            succeeded = await sandbox.call("confirm_refund", {"order_id": order_id})
            final = await session.get(Order, order_id)

            assert failed.ok is False
            assert failed.error_code == "refund_not_confirmed"
            assert observed.ok and observed.payload["status"] == "delivered"
            assert proposed.ok
            assert succeeded.ok and succeeded.payload["status"] == "refunded"
            assert final is not None and final.status == "refunded"
            assert [mutation.reason_code for mutation in sandbox.mutations()] == [
                "refund_executed"
            ]
        finally:
            await transaction.rollback()

    assert await _snapshot() == before
