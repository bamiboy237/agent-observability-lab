import json
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from starlette.requests import Request

from app.domain.support.errors import Forbidden, OrderNotFound
from app.domain.support.schemas import OrderRead, OrderStatus
from app.domain.support.service import SupportService
from app.errors import application_exception_handler
from tests.fakes.support_repository import InMemorySupportRepository


def make_order(owner_id: UUID | None = None) -> OrderRead:
    return OrderRead(
        id=uuid4(),
        customer_id=owner_id or uuid4(),
        status=OrderStatus.SHIPPED,
        total_amount=Decimal("135.00"),
    )


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/orders/test",
            "raw_path": b"/orders/test",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    request.state.request_id = "review-1.4"
    return request


async def test_owner_can_look_up_their_order() -> None:
    order = make_order()
    service = SupportService(InMemorySupportRepository((order,)))

    result = await service.get_order(order.id, order.customer_id)

    assert isinstance(result, OrderRead)
    assert result == order


async def test_missing_order_raises_typed_order_not_found() -> None:
    service = SupportService(InMemorySupportRepository())

    with pytest.raises(OrderNotFound) as error:
        await service.get_order(uuid4(), uuid4())

    assert error.value.code == "order_not_found"
    assert error.value.status_code == 404

    response = await application_exception_handler(make_request(), error.value)

    assert response.status_code == 404
    assert json.loads(bytes(response.body)) == {
        "error": {"code": "order_not_found", "message": "The order was not found"},
        "request_id": "review-1.4",
    }


async def test_forbidden_maps_to_safe_http_body_without_order_data() -> None:
    order = make_order()
    service = SupportService(InMemorySupportRepository((order,)))

    with pytest.raises(Forbidden) as error:
        await service.get_order(order.id, uuid4())

    response = await application_exception_handler(make_request(), error.value)

    assert response.status_code == 403
    assert error.value.code == "forbidden"
    body = json.loads(bytes(response.body))
    assert body == {
        "error": {"code": "forbidden", "message": "You are not allowed to view this order"},
        "request_id": "review-1.4",
    }
    response_text = bytes(response.body).decode()
    for private_field in (str(order.id), str(order.customer_id), str(order.total_amount)):
        assert private_field not in response_text
