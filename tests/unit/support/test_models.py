from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.support.schemas import OrderCreate, TicketCreate


@pytest.mark.parametrize(
    ("schema", "values"),
    [
        (
            OrderCreate,
            {
                "customer_id": uuid4(),
                "status": "lost",
                "total_amount": Decimal("10.00"),
            },
        ),
        (
            TicketCreate,
            {
                "customer_id": uuid4(),
                "status": "waiting_forever",
                "subject": "Where is my order?",
            },
        ),
    ],
)
def test_command_schemas_reject_invalid_status(
    schema: type[OrderCreate] | type[TicketCreate],
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(values)


def test_order_command_rejects_negative_total() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(
            customer_id=uuid4(),
            total_amount=Decimal("-0.01"),
        )
