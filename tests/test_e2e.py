import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import AccessRequest, Decision, RequestType, RequestStatus
from app.main import app
from tests.conftest import MockLLMClient


def _seed_history(
    db: Session,
    requester_id: str,
    count: int = 3,
    request_type: RequestType = RequestType.DATA_ACCESS,
    status: RequestStatus = RequestStatus.AUTO_APPROVED,
):
    """Create historical requests for a requester."""
    for i in range(count):
        req = AccessRequest(
            requester_id=requester_id,
            request_text=f"Historical request {i}",
            classification=request_type,
            classification_confidence=0.9,
            anomaly_score=0.1,
            status=status,
            recommended_approver="approver@co.com",
        )
        db.add(req)
    db.commit()


class TestEndToEndFlow:
    """End-to-end tests covering intake through decision with mocked LLM."""

    @pytest.fixture(autouse=True)
    def _override_classifier(self, mocked_llm_client: MockLLMClient):
        """Override the LLM classifier dependency with the mock."""
        mocked_llm_client.classification_result = {
            "type": "data-access",
            "confidence": 0.95,
            "resource": "finance-dashboard",
            "role": "finance-analyst",
        }
        app.dependency_overrides["app.llm.classifier.get_classifier"] = (
            lambda: mocked_llm_client
        )
        yield
        app.dependency_overrides.clear()

    def _submit_request(
        self, client: TestClient, requester_id: str, request_text: str
    ) -> dict:
        response = client.post(
            "/access-requests",
            json={"requester_id": requester_id, "request_text": request_text},
        )
        assert response.status_code == 200
        return response.json()

    def test_auto_approved_flow(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Submit a request for a requester with sufficient history -> auto-approved -> audit trail."""
        _seed_history(
            test_db_session, "alice", count=5, request_type=RequestType.DATA_ACCESS
        )

        data = self._submit_request(test_client, "alice", "Need the finance dashboard")
        assert data["status"] == "auto_approved"
        req_id = data["id"]

        # Verify database record
        req = (
            test_db_session.query(AccessRequest)
            .filter(AccessRequest.id == req_id)
            .first()
        )
        assert req is not None
        assert req.status == RequestStatus.AUTO_APPROVED
        assert req.classification == RequestType.DATA_ACCESS

        # Verify audit trail: exactly one decision with action "auto_approved"
        decisions = (
            test_db_session.query(Decision)
            .filter(Decision.access_request_id == req_id)
            .order_by(Decision.timestamp)
            .all()
        )
        assert len(decisions) == 1
        assert decisions[0].action == "auto_approved"
        assert decisions[0].actor == "system"

    def test_manual_review_then_approve(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Submit a request for a new user -> pending_review -> approve via UI -> audit trail."""
        # No history -> cold-start -> pending_review
        data = self._submit_request(test_client, "bob", "I need admin access")
        assert data["status"] == "pending_review"
        req_id = data["id"]

        # Reviewer approves via POST /detail/{id}/approve
        approve_response = test_client.post(f"/detail/{req_id}/approve")
        assert approve_response.status_code == 303  # redirect

        # Verify DB state
        req = (
            test_db_session.query(AccessRequest)
            .filter(AccessRequest.id == req_id)
            .first()
        )
        assert req is not None
        assert req.status == RequestStatus.APPROVED

        # Verify audit trail: pending_review then approved
        decisions = (
            test_db_session.query(Decision)
            .filter(Decision.access_request_id == req_id)
            .order_by(Decision.timestamp)
            .all()
        )
        assert len(decisions) == 2
        assert decisions[0].action == "pending_review"
        assert decisions[0].actor == "system"
        assert decisions[1].action == "approved"
        assert decisions[1].actor == "reviewer"

    def test_manual_review_then_reject(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Submit a request for a new user -> pending_review -> reject via UI -> audit trail."""
        data = self._submit_request(test_client, "carol", "Need something unusual")
        assert data["status"] == "pending_review"
        req_id = data["id"]

        reject_response = test_client.post(f"/detail/{req_id}/reject")
        assert reject_response.status_code == 303

        req = (
            test_db_session.query(AccessRequest)
            .filter(AccessRequest.id == req_id)
            .first()
        )
        assert req is not None
        assert req.status == RequestStatus.REJECTED

        decisions = (
            test_db_session.query(Decision)
            .filter(Decision.access_request_id == req_id)
            .order_by(Decision.timestamp)
            .all()
        )
        assert len(decisions) == 2
        assert decisions[0].action == "pending_review"
        assert decisions[1].action == "rejected"

    def test_manual_review_then_override(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Submit a request -> pending_review -> override classification and approve."""
        data = self._submit_request(test_client, "dave", "Need system access")
        assert data["status"] == "pending_review"
        req_id = data["id"]

        override_response = test_client.post(
            f"/detail/{req_id}/override",
            data={
                "classification": "system-access",
                "classification_confidence": 0.8,
            },
        )
        assert override_response.status_code == 303

        req = (
            test_db_session.query(AccessRequest)
            .filter(AccessRequest.id == req_id)
            .first()
        )
        assert req is not None
        assert req.classification == RequestType.SYSTEM_ACCESS
        assert req.classification_confidence == 0.8
        assert req.status == RequestStatus.APPROVED

        decisions = (
            test_db_session.query(Decision)
            .filter(Decision.access_request_id == req_id)
            .order_by(Decision.timestamp)
            .all()
        )
        assert len(decisions) == 2
        assert decisions[0].action == "pending_review"
        assert decisions[1].action == "approved"
        assert decisions[1].actor == "reviewer"
