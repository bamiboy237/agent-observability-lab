"""This module defines the flight-booking reference workflow.

Shape: a bounded Ctrip-style airline booking operation. The agent searches
flights and fares (safe reads), holds and confirms bookings (sensitive
writes), and the confirmation requires an explicit customer approval token
— the same gate discipline as a real 2026 travel-assistant stack where
hold/confirm are separated and the money-moving step needs human approval.
Realistic failure: the fare service times out once and the agent retries.
Missing data: an unknown route returns no flights instead of an invented
offer. Business outcome: a confirmed booking with a PNR, fare, and seat
count, measured as booking_confirmed.
"""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.reference.contracts import (
    ReferenceCandidate,
    ReferenceExpectation,
    ReferenceObservation,
    ReferencePlan,
    ReferenceToolCall,
    ReferenceWorkflow,
)
from app.domain.reference.workflows.repo import InMemoryReferenceRepository
from app.domain.simulation.faults import FaultKind, FaultScript, FaultScriptEntry

WORKFLOW_ID = "flight_booking"
NAME = "Flight booking (Ctrip-style travel assistant)"
SOURCE = (
    "Haohao-end/Ctrip-Style-AI-Travel-Assistant shape; "
    "TravelPlanner sandbox/verifier reference"
)
GATE_TOKEN = "approve-7f3a-c91d"


class Flight(BaseModel):
    """One scheduled flight with its remaining seat inventory."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    flight_number: str
    origin: str
    destination: str
    departure_time: str
    seats_total: int = Field(ge=1)
    seats_available: int = Field(ge=0)
    fare_usd: float = Field(ge=0)


class Passenger(BaseModel):
    """One passenger with a synthetic identity."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    email: str


class Booking(BaseModel):
    """One booking with its PNR and lifecycle status."""

    model_config = ConfigDict(extra="forbid")

    pnr: str
    passenger_id: UUID
    flight_id: UUID
    status: str = Field(pattern=r"^(held|confirmed|cancelled)$")
    fare_usd: float = Field(ge=0)


class AirlinePolicy(BaseModel):
    """The versioned fare and booking policy the agent must follow."""

    model_config = ConfigDict(extra="forbid")

    version: str
    price_lock_minutes: int = Field(ge=1)
    refund_window_days: int = Field(ge=0)
    max_holds_per_passenger: int = Field(ge=1)


class FlightBookingState(BaseModel):
    """The disposable state of one booking scenario."""

    model_config = ConfigDict(extra="forbid")

    flights: tuple[Flight, ...] = ()
    passengers: tuple[Passenger, ...] = ()
    bookings: tuple[Booking, ...] = ()
    policy: AirlinePolicy = Field(default_factory=lambda: AirlinePolicy(
        version="2026-07-01",
        price_lock_minutes=15,
        refund_window_days=3,
        max_holds_per_passenger=1,
    ))


def _seed() -> FlightBookingState:
    passenger_id = UUID("f1000000-0000-4000-8000-000000000001")
    return FlightBookingState(
        flights=(
            Flight(
                id=UUID("f2000000-0000-4000-8000-000000000001"),
                flight_number="CT-102",
                origin="SFO",
                destination="LAX",
                departure_time="2026-08-14T18:30:00Z",
                seats_total=180,
                seats_available=12,
                fare_usd=149.50,
            ),
            Flight(
                id=UUID("f2000000-0000-4000-8000-000000000002"),
                flight_number="CT-207",
                origin="SFO",
                destination="SEA",
                departure_time="2026-08-14T19:05:00Z",
                seats_total=120,
                seats_available=0,
                fare_usd=99.00,
            ),
        ),
        passengers=(
            Passenger(
                id=passenger_id,
                name="Alex Rivera",
                email="alex.rivera@example.invalid",
            ),
        ),
    )


class _SearchFlights:
    name = "search_flights"
    safe = True

    def run(self, repository: Any, arguments: dict[str, object]) -> str:
        state = repository._state  # noqa: SLF001  (typed via protocol in tests)
        origin = str(arguments.get("origin", ""))
        destination = str(arguments.get("destination", ""))
        matches = [
            flight
            for flight in state.flights
            if flight.origin == origin and flight.destination == destination
        ]
        if not matches:
            return "NO_FLIGHTS: no offers for the requested route; do not invent one"
        return "; ".join(
            f"{flight.flight_number} {flight.departure_time} seats={flight.seats_available}"
            for flight in matches
        )


class _GetFare:
    name = "get_fare"
    safe = True

    def run(self, repository: Any, arguments: dict[str, object]) -> str:
        state = repository._state  # noqa: SLF001
        flight = next(
            (f for f in state.flights if str(f.id) == str(arguments.get("flight_id", ""))),
            None,
        )
        if flight is None:
            return "FARE_NOT_FOUND: no fare for that flight"
        return (
            f"FARE {flight.flight_number}: ${flight.fare_usd:.2f}, lock "
            f"{state.policy.price_lock_minutes} minutes, refund within "
            f"{state.policy.refund_window_days} days"
        )


class _HoldBooking:
    name = "hold_booking"
    safe = False

    def run(self, repository: Any, arguments: dict[str, object]) -> str:
        state = repository._state  # noqa: SLF001
        passenger_id = UUID(str(arguments.get("passenger_id", "")))
        flight_id = UUID(str(arguments.get("flight_id", "")))
        flight = next((f for f in state.flights if f.id == flight_id), None)
        if flight is None or flight.seats_available <= 0:
            return "HOLD_REJECTED: no seats available"
        holds = [
            b for b in state.bookings if b.passenger_id == passenger_id and b.status == "held"
        ]
        if len(holds) >= state.policy.max_holds_per_passenger:
            return "HOLD_REJECTED: hold limit reached"
        pnr = f"PNR{uuid4().hex[:8].upper()}"
        booking = Booking(
            pnr=pnr,
            passenger_id=passenger_id,
            flight_id=flight_id,
            status="held",
            fare_usd=flight.fare_usd,
        )
        before = flight.seats_available
        updated_flight = flight.model_copy(update={"seats_available": before - 1})
        repository.replace(
            state.model_copy(
                update={
                    "flights": tuple(
                        updated_flight if f.id == flight_id else f for f in state.flights
                    ),
                    "bookings": state.bookings + (booking,),
                }
            )
        )
        repository.record(
            resource="flight",
            resource_id=str(flight_id),
            field="seats_available",
            before=before,
            after=before - 1,
            reason_code="seat_held",
        )
        repository.record(
            resource="booking",
            resource_id=pnr,
            field="created",
            before="",
            after=pnr,
            reason_code="booking_held",
        )
        return f"HELD pnr={pnr} fare={flight.fare_usd:.2f}"


class _ConfirmBooking:
    name = "confirm_booking"
    safe = False

    def run(self, repository: Any, arguments: dict[str, object]) -> str:
        state = repository._state  # noqa: SLF001
        token = str(arguments.get("customer_token", ""))
        if token != GATE_TOKEN:
            return "CONFIRM_REJECTED: customer approval required"
        pnr = str(arguments.get("pnr", ""))
        booking = next((b for b in state.bookings if b.pnr == pnr), None)
        if booking is None:
            return "CONFIRM_REJECTED: unknown booking"
        if booking.status != "held":
            return "CONFIRM_REJECTED: booking is not held"
        updated = booking.model_copy(update={"status": "confirmed"})
        repository.replace(
            state.model_copy(
                update={
                    "bookings": tuple(
                        updated if b.pnr == pnr else b for b in state.bookings
                    )
                }
            )
        )
        repository.record(
            resource="booking",
            resource_id=pnr,
            field="status",
            before="held",
            after="confirmed",
            reason_code="booking_confirmed",
        )
        return f"CONFIRMED pnr={pnr}"


class _CancelBooking:
    name = "cancel_booking"
    safe = False

    def run(self, repository: Any, arguments: dict[str, object]) -> str:
        state = repository._state  # noqa: SLF001
        pnr = str(arguments.get("pnr", ""))
        booking = next((b for b in state.bookings if b.pnr == pnr), None)
        if booking is None:
            return "CANCEL_REJECTED: unknown booking"
        updated = booking.model_copy(update={"status": "cancelled"})
        repository.replace(
            state.model_copy(
                update={
                    "bookings": tuple(
                        updated if b.pnr == pnr else b for b in state.bookings
                    )
                }
            )
        )
        repository.record(
            resource="booking",
            resource_id=pnr,
            field="status",
            before=booking.status,
            after="cancelled",
            reason_code="booking_cancelled",
        )
        return f"CANCELLED {pnr}"


SEED = _seed()

FAULT_SCRIPT = FaultScript(
    script_version="1",
    dependency="fare.service",
    entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_fare"),),
)


def _plan(gate_verified: bool) -> ReferencePlan:
    passenger_id = SEED.passengers[0].id
    flight_id = SEED.flights[0].id
    return ReferencePlan(
        routing={
            "intent": "book_flight",
            "origin": "SFO",
            "destination": "LAX",
            "confidence": 0.95,
        },
        tool_calls=(
            ReferenceToolCall(
                tool="search_flights",
                arguments={"origin": "SFO", "destination": "LAX"},
            ),
            ReferenceToolCall(tool="get_fare", arguments={"flight_id": str(flight_id)}),
            ReferenceToolCall(
                tool="hold_booking",
                arguments={"passenger_id": str(passenger_id), "flight_id": str(flight_id)},
            ),
            ReferenceToolCall(
                tool="confirm_booking",
                arguments={
                    "pnr": "$hold_booking.pnr",
                    "customer_token": GATE_TOKEN if gate_verified else "no-token",
                },
            ),
        ),
        gate_verified=gate_verified,
    )


def _observe(state: object, mutations: tuple[dict[str, object], ...]) -> ReferenceObservation:
    """This function derives the outcome from the observed booking state.

    ``booking_confirmed`` is claimed only when the state contains a booking
    whose status is confirmed and the mutation trail shows the
    held->confirmed transition.
    """
    bookings = []
    if isinstance(state, dict):
        bookings = [
            booking
            for booking in state.get("bookings", [])
            if isinstance(booking, dict)
        ]
    confirmed = [b for b in bookings if b.get("status") == "confirmed"]
    held = [b for b in bookings if b.get("status") == "held"]
    flights = state.get("flights", []) if isinstance(state, dict) else []
    seats_after = None
    if isinstance(state, dict):
        for flight in flights:
            if isinstance(flight, dict) and flight.get("flight_number") == "CT-102":
                seats_after = flight.get("seats_available")
    if confirmed:
        return ReferenceObservation(
            outcome="completed",
            reason_code="booking_confirmed",
            business_outcome="booking_confirmed",
            metrics={
                "pnr": confirmed[0].get("pnr", ""),
                "fare_usd": confirmed[0].get("fare_usd", 0.0),
                "seats_after": seats_after if seats_after is not None else len(bookings),
            },
        )
    if held:
        return ReferenceObservation(
            outcome="blocked",
            reason_code="booking_held",
            business_outcome="booking_held_not_confirmed",
            metrics={"holds": len(held)},
        )
    return ReferenceObservation(
        outcome="failed",
        reason_code="no_booking",
        business_outcome="failed",
        metrics={},
    )


def build_workflow() -> ReferenceWorkflow:
    """This function returns the flight-booking reference workflow."""
    return ReferenceWorkflow(
        workflow_id=WORKFLOW_ID,
        name=NAME,
        source=SOURCE,
        seed_state=SEED,
        repository=InMemoryReferenceRepository(),
        tools=(
            _SearchFlights(),
            _GetFare(),
            _HoldBooking(),
            _ConfirmBooking(),
            _CancelBooking(),
        ),
        expectation=ReferenceExpectation(
            outcome="completed",
            reason_codes=("booking_confirmed",),
            permitted_transitions=("booking:created", "booking:held->confirmed"),
            required_transitions=("booking:held->confirmed",),
            gate_required=True,
            gate_tool="confirm_booking",
            protected_tools=("confirm_booking",),
        ),
        baseline_plan=_plan(gate_verified=True),
        candidate_plan=_plan(gate_verified=False),
        observer=_observe,
        candidate=ReferenceCandidate(
            name="Remove customer approval gate",
            change_type="confirmation_gate",
            baseline_label="gate-required",
            candidate_label="auto-confirm",
        ),
        fault_script=FAULT_SCRIPT,
        reused_code=(
            "SimulationEventCollector + SimulationEvent allowlist",
            "FaultScript / FaultScriptEntry schema",
            "ComparisonVerdict / CriterionDelta from comparison.compare",
            "InMemoryReferenceRepository pattern (mirrors tests.fakes provisioner)",
        ),
        integration_note=(
            "The booking agent, tools, state, and policy are workflow-local; the "
            "support-shaped bundle/runner/case-library contracts are not reused "
            "because they encode support types (orders/tickets/policies)."
        ),
    )
