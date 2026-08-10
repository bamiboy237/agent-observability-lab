"""Prove that the sandbox uses real SQL and leaves no persistent changes."""

import os

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import func, select, text

from app.config import Settings
from app.db import get_session_factory
from app.domain.simulation.postgres import PostgresSandboxTarget, PostgresSupportSandbox
from app.domain.simulation.scenarios import SCENARIO_BY_ID
from app.domain.support.models import Order, Ticket


@pytest.fixture(scope="module", autouse=True)
def apply_migrations() -> None:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for simulation integration tests")
    if settings.environment != "test" or os.environ.get("RUN_DATABASE_TESTS") != "1":
        pytest.skip("set ENVIRONMENT=test and RUN_DATABASE_TESTS=1 for an isolated database")
    command.upgrade(Config("alembic.ini"), "head")


async def _stored_snapshot() -> tuple[list[tuple[object, object]], int]:
    async with get_session_factory()() as session:
        orders = (
            await session.execute(select(Order.id, Order.status).order_by(Order.id))
        ).all()
        ticket_count = await session.scalar(select(func.count()).select_from(Ticket))
    return list(orders), ticket_count or 0


@pytest.mark.integration
async def test_postgres_sandbox_uses_real_services_and_rolls_back() -> None:
    before = await _stored_snapshot()
    original = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]
    scenario = original.model_copy(
        update={
            "request": original.request.model_copy(update={"refund_confirmed": True}),
            "content_hash": None,
        }
    )
    order_id = scenario.initial_state.orders[0].id
    settings = Settings()  # type: ignore[call-arg]
    target = PostgresSandboxTarget.from_database_url(
        str(settings.database_url),
        environment=settings.environment,
    )

    async with get_session_factory()() as session:
        transaction = await session.begin()
        try:
            sandbox = PostgresSupportSandbox(
                session,
                scenario,
                isolation_confirmed=True,
                target=target,
            )
            await sandbox.seed(scenario.initial_state)

            read = await sandbox.call("get_order_status", {"order_id": order_id})
            proposal = await sandbox.call(
                "propose_refund",
                {"order_id": order_id, "reason": "Customer requested a refund"},
            )
            refund = await sandbox.call("confirm_refund", {"order_id": order_id})
            ticket = await sandbox.call("escalate", {"subject": "Review completed refund"})

            stored_order = await session.get(Order, order_id)
            stored_ticket_count = await session.scalar(select(func.count()).select_from(Ticket))
            assert read.ok and read.payload["status"] == "delivered"
            assert proposal.ok
            assert refund.ok and refund.payload["status"] == "refunded"
            assert ticket.ok
            assert stored_order is not None and stored_order.status == "refunded"
            assert stored_ticket_count == 1
            assert [mutation.reason_code for mutation in sandbox.mutations()] == [
                "refund_executed",
                "ticket_created",
            ]

            backend_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            async with get_session_factory()() as lock_session:
                persistent_table_locks = await lock_session.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_locks AS lock
                        JOIN pg_class AS relation ON relation.oid = lock.relation
                        JOIN pg_namespace AS namespace
                            ON namespace.oid = relation.relnamespace
                        WHERE lock.pid = :backend_pid
                          AND namespace.nspname NOT LIKE 'pg_temp_%'
                          AND relation.relname IN (
                              'customers', 'orders', 'tickets', 'policy_documents'
                          )
                        """
                    ),
                    {"backend_pid": backend_pid},
                )
            assert persistent_table_locks == 0

            persistent_orders = (
                await session.execute(
                    text("SELECT id, status FROM public.orders ORDER BY id")
                )
            ).all()
            persistent_ticket_count = await session.scalar(
                text("SELECT count(*) FROM public.tickets")
            )
            assert list(persistent_orders) == before[0]
            assert persistent_ticket_count == before[1]

            await sandbox.reset()
            restored_order = await session.get(Order, order_id)
            restored_ticket_count = await session.scalar(select(func.count()).select_from(Ticket))
            assert restored_order is not None and restored_order.status == "delivered"
            assert restored_ticket_count == 0
            assert sandbox.mutations() == ()
        finally:
            await transaction.rollback()

    assert await _stored_snapshot() == before
