import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AccessRequest, RequestType, RequestStatus
from app.main import app
from tests.conftest import MockLLMClient

pytestmark = pytest.mark.usefixtures("test_db_session")


def _seed_history(
    db: Session,
    requester_id: str,
    count: int = 3,
    request_type: RequestType = RequestType.DATA_ACCESS,
    status: RequestStatus = RequestStatus.AUTO_APPROVED,
):
    """Create `count` historical requests for a requester, all of the given type and status."""
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


class TestRoutingThresholdBoundaries:
    """Tests for auto-approve vs manual-review routing based on anomaly score thresholds."""

    @pytest.fixture(autouse=True)
    def override_classifier(self, mocked_llm_client: MockLLMClient):
        """Replace the real classifier with a deterministic mock that returns a valid classification."""
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

    def test_no_history_returns_pending_review(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Requester with no prior requests gets cold-start high anomaly -> manual review."""
        data = self._submit_request(
            test_client, "new_user", "Need access to sales data"
        )
        assert data["status"] == "pending_review"

    def test_low_anomaly_auto_approved(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Requester with many same-type requests gets low anomaly -> auto-approved."""
        _seed_history(test_db_session, "alice", request_type=RequestType.DATA_ACCESS)
        data = self._submit_request(
            test_client, "alice", "I need the finance dashboard"
        )
        assert data["status"] == "auto_approved"

    def test_high_anomaly_returns_pending_review(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Requester with history but new type gets high anomaly -> manual review."""
        _seed_history(test_db_session, "bob", request_type=RequestType.APP_ACCESS)
        data = self._submit_request(test_client, "bob", "Need admin on production")
        assert data["status"] == "pending_review"

    def test_anomaly_below_threshold_auto_approved(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Exact anomaly score just below the default threshold (0.5) -> auto-approved."""
        # Seed enough history to drive anomaly low (the actual score depends on heuristic)
        _seed_history(
            test_db_session, "carol", count=5, request_type=RequestType.DATA_ACCESS
        )
        data = self._submit_request(test_client, "carol", "Need read-only finance")
        assert data["status"] == "auto_approved"
        assert data["anomaly_score"] < settings.anomaly_threshold

    def test_anomaly_above_threshold_pending_review(
        self, test_client: TestClient, test_db_session: Session
    ):
        """Anomaly score above the default threshold -> manual review."""
        # Single history of a different type -> anomaly likely high
        _seed_history(
            test_db_session, "dave", count=1, request_type=RequestType.SYSTEM_ACCESS
        )
        data = self._submit_request(test_client, "dave", "I need another system access")
        assert data["status"] == "pending_review"
        assert data["anomaly_score"] >= settings.anomaly_threshold

    def test_low_anomaly_but_no_role_mapping_pending_review(
        self,
        test_client: TestClient,
        mocked_llm_client: MockLLMClient,
        test_db_session: Session,
    ):
        """Even with low anomaly, if no role mapping is found, route to review."""
        _seed_history(test_db_session, "eve", request_type=RequestType.DATA_ACCESS)
        # Configure mock to return a resource that doesn't match any role in seed
        mocked_llm_client.classification_result = {
            "type": "data-access",
            "confidence": 0.95,
            "resource": "nonexistent-resource",
            "role": "unknown-role",
        }
        data = self._submit_request(test_client, "eve", "I need the magic dashboard")
        assert data["status"] == "pending_review"

    def test_low_anomaly_but_low_confidence_pending_review(
        self,
        test_client: TestClient,
        mocked_llm_client: MockLLMClient,
        test_db_session: Session,
    ):
        """Even with low anomaly, if classification confidence is low, route to review."""
        _seed_history(test_db_session, "frank", request_type=RequestType.DATA_ACCESS)
        mocked_llm_client.classification_result = {
            "type": "data-access",
            "confidence": 0.3,  # below confidence threshold
            "resource": "finance-dashboard",
            "role": "finance-analyst",
        }
        data = self._submit_request(test_client, "frank", "Something about data")
        assert data["status"] == "pending_review"
