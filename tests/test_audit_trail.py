import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import AccessRequest, Decision, RequestStatus, RequestType
from app.main import app
from tests.conftest import MockLLMClient

pytestmark = pytest.mark.usefixtures("test_db_session")


def _seed_requests(
    db: Session,
    requester_id: str,
    count: int = 3,
    request_type: RequestType = RequestType.DATA_ACCESS,
    status: RequestStatus = RequestStatus.AUTO_APPROVED,
) -> None:
    """Insert `count` historical approved requests for a requester."""
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


class TestPersistenceAndAuditTrail:
    """
    Tests verifying that every state transition is persisted correctly:
    creation, auto-approval, manual approval, rejection, and override.
    Also verifies that the decisions table records the actor and timestamp.
    """

    @pytest.fixture(autouse=True)
    def _override_classifier(self, mocked_llm_client: MockLLMClient):
        """Replace the real classifier with a deterministic mock."""
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
        """Helper to submit a request and return the response JSON."""
        response = client.post(
            "/access-requests",
            json={"requester_id": requester_id, "request_text": request_text},
        )
        assert response.status_code == 200
        return response.json()

    # ----------------------------------------------------------------
    # Creation persistence
    # ----------------------------------------------------------------

    def test_request_persisted_on_submission(
        self, test_client: TestClient, test_db_session: Session
    ):
        """After submitting a request via POST, the record exists in the database."""
        data = self._submit_request(test_client, "alice", "Need the finance dashboard")
        req_id = data["id"]
        req = (
            test_db_session.query(AccessRequest)
            .filter(AccessRequest.id == req_id)
            .first()
        )
        assert req is not None
        assert req.requester_id == "alice"
        assert req.request_text == "Need the finance dashboard"
        assert req.classification == RequestType.DATA_ACCESS
        assert req.classification_confidence == 0.95
        assert req.anomaly_score is not None
        assert req.status is not None

    def test_decision_created_on_auto_approval(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Auto-approved requests create a Decision record with actor 'system'."""
        # Seed history so anomaly is low -> auto-approve
        _seed_requests(test_db_session, "bob", count=5)
        data = self._submit_request(test_client, "bob", "I need more data")
        assert data["status"] == "auto_approved"
        req = (
            test_db_session.query(AccessRequest)
            .filter(AccessRequest.id == data["id"])
            .first()
        )
        assert req is not None
        # Check the decisions linked to this request
        decisions = (
            test_db_session.query(Decision)
            .filter(Decision.access_request_id == req.id)
            .order_by(Decision.timestamp)
            .all()
        )
        assert len(decisions) > 0
        auto_decision = next(
            (d for d in decisions if d.action == "auto_approved"), None
        )
        assert auto_decision is not None
        assert auto_decision.actor == "system"
        assert auto_decision.timestamp is not None

    def test_decision_created_on_pending_review(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Requests routed to manual review get a 'pending_review' decision."""
        data = self._submit_request(test_client, "carol", "Admin on production")
        assert data["status"] == "pending_review"
        req = (
            test_db_session.query(AccessRequest)
            .filter(AccessRequest.id == data["id"])
            .first()
        )
        assert req is not None
        decision = (
            test_db_session.query(Decision)
            .filter(
                Decision.access_request_id == req.id,
                Decision.action == "pending_review",
            )
            .first()
        )
        assert decision is not None
        assert decision.actor == "system"

    # ----------------------------------------------------------------
    # Manual approval / rejection via UI
    # ----------------------------------------------------------------

    def test_manual_approval_creates_decision(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Manually approving a pending request creates a Decision with actor 'reviewer'."""
        data = self._submit_request(test_client, "dave", "Need VPN access")
        assert data["status"] == "pending_review"
        req_id = data["id"]
        response = test_client.post(f"/detail/{req_id}/approve")
        assert response.status_code == 303
        # Retrieve the decision from DB
        decision = (
            test_db_session.query(Decision)
            .filter(
                Decision.access_request_id == req_id,
                Decision.action == "approved",
            )
            .first()
        )
        assert decision is not None
        assert decision.actor == "reviewer"
        assert decision.timestamp is not None

    def test_manual_rejection_creates_decision(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Manually rejecting a pending request creates a Decision with action 'rejected'."""
        data = self._submit_request(test_client, "eve", "I need something")
        assert data["status"] == "pending_review"
        req_id = data["id"]
        response = test_client.post(f"/detail/{req_id}/reject")
        assert response.status_code == 303
        decision = (
            test_db_session.query(Decision)
            .filter(
                Decision.access_request_id == req_id,
                Decision.action == "rejected",
            )
            .first()
        )
        assert decision is not None
        assert decision.actor == "reviewer"

    def test_override_creates_decision_and_updates_classification(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Override changes classification and creates an 'approved' decision."""
        data = self._submit_request(test_client, "frank", "Need system account")
        assert data["status"] == "pending_review"
        req_id = data["id"]
        response = test_client.post(
            f"/detail/{req_id}/override",
            data={
                "classification": "system-access",
                "classification_confidence": 0.85,
            },
        )
        assert response.status_code == 303
        # Check request updated in DB
        req = (
            test_db_session.query(AccessRequest)
            .filter(AccessRequest.id == req_id)
            .first()
        )
        assert req is not None
        assert req.classification == RequestType.SYSTEM_ACCESS
        assert req.classification_confidence == 0.85
        # Check decision
        decision = (
            test_db_session.query(Decision)
            .filter(
                Decision.access_request_id == req_id,
                Decision.action == "approved",
            )
            .first()
        )
        assert decision is not None
        assert decision.actor == "reviewer"

    # ----------------------------------------------------------------
    # State transition enforcement
    # ----------------------------------------------------------------

    def test_cannot_approve_already_approved_request(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Attempting to approve a non-pending request returns 400 and no new decision."""
        # Create an auto-approved request (low anomaly)
        _seed_requests(test_db_session, "grace", count=5)
        data = self._submit_request(test_client, "grace", "More data")
        assert data["status"] == "auto_approved"
        req_id = data["id"]
        response = test_client.post(f"/detail/{req_id}/approve")
        assert response.status_code == 400
        # No extra 'approved' decision should exist (only auto_approved from creation)
        decisions = (
            test_db_session.query(Decision)
            .filter(Decision.access_request_id == req_id)
            .all()
        )
        assert len(decisions) == 1
        assert decisions[0].action == "auto_approved"

    def test_cannot_reject_already_rejected_request(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Attempting to reject a rejected request returns 400."""
        # Create pending, then reject
        data = self._submit_request(test_client, "heidi", "Test")
        req_id = data["id"]
        test_client.post(f"/detail/{req_id}/reject")
        response = test_client.post(f"/detail/{req_id}/reject")
        assert response.status_code == 400

    def test_cannot_override_non_pending_request(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Overriding an auto-approved request returns 400."""
        _seed_requests(test_db_session, "ivan", count=5)
        data = self._submit_request(test_client, "ivan", "More data")
        assert data["status"] == "auto_approved"
        req_id = data["id"]
        response = test_client.post(
            f"/detail/{req_id}/override",
            data={"classification": "data-access", "classification_confidence": 0.9},
        )
        assert response.status_code == 400

    # ----------------------------------------------------------------
    # Audit trail queryability
    # ----------------------------------------------------------------

    def test_audit_trail_ordered_by_timestamp(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Decisions for a request are returned in chronological order."""
        data = self._submit_request(test_client, "judy", "Need access")
        req_id = data["id"]
        # Approve via UI
        test_client.post(f"/detail/{req_id}/approve")
        decisions = (
            test_db_session.query(Decision)
            .filter(Decision.access_request_id == req_id)
            .order_by(Decision.timestamp)
            .all()
        )
        assert len(decisions) >= 2
        # First should be pending_review, second approved
        assert decisions[0].action == "pending_review"
        assert decisions[0].actor == "system"
        assert decisions[-1].action == "approved"
        assert decisions[-1].actor == "reviewer"
        for i in range(len(decisions) - 1):
            assert decisions[i].timestamp <= decisions[i + 1].timestamp

    def test_audit_trail_includes_override_classification_change(
        self, test_client: TestClient, test_db_session: Session
    ):
        """An override decision appears alongside the original pending_review."""
        data = self._submit_request(test_client, "karen", "Something")
        req_id = data["id"]
        test_client.post(
            f"/detail/{req_id}/override",
            data={
                "classification": "privilege-elevation",
                "classification_confidence": 0.8,
            },
        )
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
