"""This script runs one order-status or refund case manually with a hosted model.

Usage:
    uv run python scripts/manual_agent.py order-status
    uv run python scripts/manual_agent.py refund
    uv run python scripts/manual_agent.py refund-confirmed

The script requires these environment variables:
    MODEL_PROVIDER=<openai|anthropic>
    MODEL_NAME=<model>
    MODEL_API_KEY=<key>
    Optional: MODEL_BASE_URL, OTEL_TRACING_ENABLED, LANGSMITH_TRACING,
    LANGSMITH_API_KEY=<key>
    LANGSMITH_PROJECT=<project>

The cases use an in-memory repository.
The repository contains records that match the Phase 1 seed.
The cases do not require a database.
The deterministic Phase 1 seed supplies identifiers for orders and customers.
"""

import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from app.adapters.pydantic_ai_agent import ModelConfig, PydanticAISupportAgent
from app.config import Settings
from app.domain.agent.instructions import POLICY_SLUG
from app.domain.agent.schemas import SupportRequest
from app.domain.support.schemas import (
    OrderRead,
    OrderStatus,
    PolicyDocumentRead,
    TicketCreate,
    TicketRead,
)
from app.domain.support.seed import POLICY_CONTENT, seed_id
from app.telemetry.config import build_tracer, reset_trace_cache
from app.telemetry.recorder import TraceRecorder


class SeedRepository:
    """This repository stores minimal records for manual runs.

    The repository does not import modules from tests/.
    """

    def __init__(self) -> None:
        alex = seed_id("customer:alex-rivera")
        samira = seed_id("customer:samira-patel")
        self.orders: dict[UUID, OrderRead] = {
            seed_id("order:shipped"): OrderRead(
                id=seed_id("order:shipped"),
                customer_id=alex,
                status=OrderStatus.SHIPPED,
                total_amount=Decimal("135.00"),
            ),
            seed_id("order:delivered"): OrderRead(
                id=seed_id("order:delivered"),
                customer_id=samira,
                status=OrderStatus.DELIVERED,
                total_amount=Decimal("48.25"),
            ),
        }
        self.policies: dict[UUID, PolicyDocumentRead] = {
            seed_id("policy:refund-and-delivery:2026-07-30"): PolicyDocumentRead(
                id=seed_id("policy:refund-and-delivery:2026-07-30"),
                slug=POLICY_SLUG,
                version="2026-07-30",
                title="Refund and Delivery Policy",
                content=POLICY_CONTENT,
                content_hash="",
            ),
        }
        self.tickets: dict[UUID, TicketRead] = {}

    async def get_order(self, order_id: UUID) -> OrderRead | None:
        return self.orders.get(order_id)

    async def save_order(self, order: OrderRead) -> OrderRead | None:
        self.orders[order.id] = order
        return order

    async def get_policy(
        self,
        slug: str,
        version: str | None = None,
    ) -> PolicyDocumentRead | None:
        matches = [
            policy
            for policy in self.policies.values()
            if policy.slug == slug and (version is None or policy.version == version)
        ]
        return max(matches, key=lambda policy: policy.version) if matches else None

    async def create_ticket(self, ticket: TicketCreate) -> TicketRead:
        created = TicketRead(id=uuid4(), **ticket.model_dump())
        self.tickets[created.id] = created
        return created

    async def get_ticket(self, ticket_id: UUID) -> TicketRead | None:
        return self.tickets.get(ticket_id)


def _make_request(case: str) -> SupportRequest:
    if case == "order-status":
        return SupportRequest(
            customer_id=seed_id("customer:alex-rivera"),
            message=f"Where is my order {seed_id('order:shipped')}?",
        )
    if case in {"refund", "refund-confirmed"}:
        return SupportRequest(
            customer_id=seed_id("customer:samira-patel"),
            message=f"My order {seed_id('order:delivered')} arrived damaged. Please refund it.",
            refund_confirmed=case == "refund-confirmed",
        )
    print(f"Unknown case: {case}", file=sys.stderr)
    sys.exit(1)


async def main() -> None:
    reset_trace_cache()
    case = sys.argv[1] if len(sys.argv) > 1 else "order-status"
    if case not in ("order-status", "refund", "refund-confirmed"):
        print(f"Usage: {sys.argv[0]} order-status|refund|refund-confirmed", file=sys.stderr)
        sys.exit(1)

    env_file = Path(".env")
    _env_file = env_file if env_file.exists() else None
    settings = Settings(  # type: ignore[call-arg]
        _env_file=_env_file,
    )

    if not settings.model_configured:
        print(
            "MODEL_PROVIDER and MODEL_NAME are required. Set MODEL_API_KEY for hosted endpoints.",
            file=sys.stderr,
        )
        sys.exit(1)

    tracer = build_tracer(settings)
    recorder = TraceRecorder(tracer)
    repository = SeedRepository()

    agent = PydanticAISupportAgent(
        model_config=ModelConfig(
            provider=settings.model_provider,  # type: ignore[arg-type]
            name=settings.model_name,  # type: ignore[arg-type]
            base_url=settings.model_base_url,
            api_key=settings.model_api_key,
        ),
        recorder=recorder,
        repository=repository,  # type: ignore[arg-type]
    )

    request = _make_request(case)
    print(f"Case: {case}")
    print(f"Message: {request.message}")
    print()

    response = await agent.handle(request)

    print(f"Intent:    {response.intent.value}")
    print(f"Outcome:   {response.outcome.value}")
    print(f"Reason:    {response.reason_code.value}")
    print(f"Trace ID:  {response.trace_id}")
    print(f"Message:   {response.message}")
    if response.context.order is not None:
        print(f"Order:     {response.context.order.id} ({response.context.order.status.value})")
    if response.context.policy is not None:
        print(f"Policy:    {response.context.policy.version}")

    if recorder.enabled:
        trace_id = recorder.current_trace_id()
        if trace_id:
            print(f"Trace:     {trace_id}")

    reset_trace_cache()


if __name__ == "__main__":
    asyncio.run(main())
