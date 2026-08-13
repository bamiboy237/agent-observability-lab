"""HTTP integration proof for checkpoint 6.5 review operations."""

import asyncio

from fastapi.testclient import TestClient

from app.api.dependencies import get_failure_review_service
from app.config import Settings
from app.domain.failures.dataset import load_failure_dataset
from app.domain.failures.features import extract_candidates
from app.domain.failures.grouping import group_candidates
from app.domain.failures.repository import InMemoryFailureReviewRepository
from app.domain.failures.schemas import ReviewDecision
from app.domain.failures.service import FailureReviewService
from app.main import create_app


def test_failure_group_list_detail_and_review_routes() -> None:
    dataset = load_failure_dataset()
    result = group_candidates(
        extract_candidates(dataset.traces, dataset_version=1), min_samples=1
    )
    service = FailureReviewService(InMemoryFailureReviewRepository())
    proposals = asyncio.run(service.propose_groups(result))
    proposal = proposals[0]
    app = create_app(
        Settings(
            database_url="postgresql://user:password@localhost:5432/app",
            _env_file=None,
        )
    )
    app.dependency_overrides[get_failure_review_service] = lambda: service
    with TestClient(app) as client:
        listing = client.get("/failure-groups")
        detail = client.get(f"/failure-groups/{proposal.proposal_id}")
        reviewed = client.post(
            f"/failure-groups/{proposal.proposal_id}/review",
            json={
                "decision": ReviewDecision.CONFIRM.value,
                "reviewer": "reviewer-1",
                "reason": "evidence checked",
            },
        )
        duplicate = client.post(
            f"/failure-groups/{proposal.proposal_id}/review",
            json={
                "decision": ReviewDecision.REJECT.value,
                "reviewer": "reviewer-2",
                "reason": "conflicting review",
            },
        )
    assert listing.status_code == 200
    assert detail.status_code == 200
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "confirmed"
    assert duplicate.status_code == 409
