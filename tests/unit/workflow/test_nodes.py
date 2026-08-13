"""Unit tests for isolated workflow node factories."""

from uuid import uuid4

import pytest

from app.domain.agent.schemas import RouteIntent, RoutingDecision
from app.domain.support.schemas import OrderRead, PolicyDocumentRead, TicketRead
from app.domain.workflow.errors import TransientModelError, TransientRetrievalError
from app.domain.workflow.models import SupportState, WorkflowRequest
from app.domain.workflow.nodes import (
    WorkflowNodeDependencies,
    make_order_node,
    make_route_node,
)
from app.telemetry.recorder import TraceRecorder


class RouterFake:
    def __init__(self, result: RoutingDecision | None = None) -> None:
        self.result = result or RoutingDecision(intent=RouteIntent.POLICY, confidence=1.0)
        self.calls = 0

    async def route(self, message: str) -> RoutingDecision:
        del message
        self.calls += 1
        return self.result


class RetryingRouter(RouterFake):
    def __init__(self) -> None:
        super().__init__()

    async def route(self, message: str) -> RoutingDecision:
        del message
        self.calls += 1
        if self.calls < 3:
            raise TransientModelError("model unavailable")
        return self.result


class FailingRetriever:
    def __init__(self) -> None:
        self.calls = 0

    async def get_order(self, order_id: object, actor_id: object) -> OrderRead:
        del order_id, actor_id
        self.calls += 1
        raise TransientRetrievalError("retrieval unavailable")


class Noop:
    async def get_policy(self, slug: str) -> PolicyDocumentRead:
        del slug
        raise AssertionError("not used")

    async def generate(self, *args: object) -> str:
        del args
        raise AssertionError("not used")

    async def propose(self, *args: object) -> object:
        del args
        raise AssertionError("not used")

    async def execute(self, *args: object) -> OrderRead:
        del args
        raise AssertionError("not used")

    async def escalate(self, *args: object) -> TicketRead:
        del args
        raise AssertionError("not used")


def dependencies(router: object, retriever: object | None = None) -> WorkflowNodeDependencies:
    return WorkflowNodeDependencies(
        router=router,  # type: ignore[arg-type]
        order_retriever=retriever or Noop(),  # type: ignore[arg-type]
        policy_retriever=Noop(),  # type: ignore[arg-type]
        response_generator=Noop(),  # type: ignore[arg-type]
        refund_proposer=Noop(),  # type: ignore[arg-type]
        refund_executor=Noop(),  # type: ignore[arg-type]
        escalator=Noop(),  # type: ignore[arg-type]
        recorder=TraceRecorder(None),
    )


def state(route: RoutingDecision | None = None) -> SupportState:
    actor_id = uuid4()
    return {
        "workflow_id": "workflow",
        "run_id": "run",
        "request": WorkflowRequest(actor_id=actor_id, request_id="request", message="hello"),
        "route": route or RoutingDecision(intent=RouteIntent.POLICY, confidence=1.0),
        "status": "received",
        "transcript": (),
    }


async def test_route_node_returns_delta_without_mutating_input() -> None:
    original = state()
    original.pop("route")
    result = await make_route_node(dependencies(RouterFake()))(original)

    assert "route" in result
    assert "route" not in original
    assert result["transcript"][0].changed_keys == ("route",)


async def test_retryable_model_failure_uses_bounded_retries() -> None:
    router = RetryingRouter()
    node = make_route_node(dependencies(router))
    with pytest.raises(TransientModelError):
        await node(state())
    result = await node(state())

    # The node itself escalates at its second attempt. LangGraph's retry policy
    # re-invokes it once after the first transient error.
    assert result["escalation"].reason_code == "model_retry_exhausted"


async def test_retryable_retrieval_failure_escalates_after_exhaustion() -> None:
    order_id = uuid4()
    route = RoutingDecision(
        intent=RouteIntent.ORDER_STATUS,
        confidence=1.0,
        order_id=order_id,
    )
    deps = dependencies(RouterFake(), FailingRetriever())
    node = make_order_node(deps)
    with pytest.raises(TransientRetrievalError):
        await node(state(route))
    result = await node(state(route))
    assert result["escalation"].reason_code == "retrieval_retry_exhausted"
