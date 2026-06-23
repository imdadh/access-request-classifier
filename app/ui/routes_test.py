import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, AccessRequest, RequestType, RequestStatus
from app.db.session import get_db
from app.main import app


@pytest.fixture
def test_db_session():
    """Create an in-memory SQLite database, create tables, yield a session, then drop.

    Uses StaticPool + check_same_thread=False so the single in-memory DB is shared
    with the TestClient's worker thread. Function-scoped for per-test isolation.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db_session: Session):
    """Return a TestClient with the get_db dependency overridden to use the test session."""

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    # follow_redirects=False so POST actions that return 303 are asserted directly
    # rather than being transparently followed to the redirected GET (200).
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_request(
    db: Session,
    requester_id: str = "alice",
    request_text: str = "Need access to finance dashboard",
    classification: RequestType = RequestType.DATA_ACCESS,
    classification_confidence: float = 0.9,
    anomaly_score: float = 0.2,
    status: RequestStatus = RequestStatus.PENDING_REVIEW,
    recommended_approver: str = "approver@company.com",
    anomaly_factors: str | None = None,
) -> AccessRequest:
    """Insert a bare AccessRequest record for test setup."""
    req = AccessRequest(
        requester_id=requester_id,
        request_text=request_text,
        classification=classification,
        classification_confidence=classification_confidence,
        anomaly_score=anomaly_score,
        status=status,
        recommended_approver=recommended_approver,
        anomaly_factors=anomaly_factors,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSubmitForm:
    """Tests for GET / (end-user submission form)."""

    def test_submit_form_renders_with_empty_recent_requests(self, client: TestClient):
        """The submission form renders with an empty recent requests list when no requests exist."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        # Verify the response contains the form elements (basic check)
        assert (
            b'repository"' in response.content
            or b"submit" in response.content
            or b"request" in response.content.lower()
        )

    def test_submit_form_shows_recent_requests(
        self, client: TestClient, test_db_session: Session
    ):
        """The submission form lists up to 10 most recent requests."""
        _create_request(
            test_db_session, requester_id="bob", request_text="Need VPN access"
        )
        _create_request(
            test_db_session, requester_id="carol", request_text="I need admin on prod"
        )
        response = client.get("/")
        assert response.status_code == 200
        # Check that request texts appear somewhere in the rendered HTML
        content_lower = response.content.decode().lower()
        assert "need vpn access" in content_lower
        assert "i need admin on prod" in content_lower


class TestReviewQueue:
    """Tests for GET /queue (reviewer queue)."""

    def test_queue_shows_only_pending_requests(
        self, client: TestClient, test_db_session: Session
    ):
        """Only requests with status pending_review appear in the queue."""
        pending = _create_request(
            test_db_session, requester_id="alice", status=RequestStatus.PENDING_REVIEW
        )
        approved = _create_request(
            test_db_session, requester_id="bob", status=RequestStatus.APPROVED
        )
        _create_request(
            test_db_session, requester_id="carol", status=RequestStatus.REJECTED
        )
        _create_request(
            test_db_session, requester_id="dave", status=RequestStatus.AUTO_APPROVED
        )

        response = client.get("/queue")
        assert response.status_code == 200
        content = response.content.decode()
        # The pending request should appear (by requester_id or text)
        assert pending.requester_id in content
        # Non-pending requests should not appear
        assert approved.requester_id not in content

    def test_queue_returns_200_with_no_pending(self, client: TestClient):
        """When no pending requests exist, the queue page still renders successfully."""
        response = client.get("/queue")
        assert response.status_code == 200
        # Should show some indication of empty queue (e.g., "No pending requests")
        assert (
            b"pending" in response.content.lower() or b"no" in response.content.lower()
        )


class TestReviewDetail:
    """Tests for GET /detail/{request_id}."""

    def test_detail_renders_full_context(
        self, client: TestClient, test_db_session: Session
    ):
        """The detail page shows request text, classification, anomaly score, and factors."""
        req = _create_request(
            test_db_session,
            requester_id="alice",
            request_text="I need admin access to the database",
            classification=RequestType.PRIVILEGE_ELEVATION,
            classification_confidence=0.85,
            anomaly_score=0.75,
            anomaly_factors='["Requester has never requested privilege-elevation before", "Resource not previously accessed"]',
        )
        response = client.get(f"/detail/{req.id}")
        assert response.status_code == 200
        content = response.content.decode()
        assert "I need admin access to the database" in content
        assert "privilege-elevation" in content or "Privilege Elevation" in content
        assert "0.75" in content or "75%" in content or "anomaly" in content.lower()
        # Check anomaly factors are rendered
        assert "Requester has never requested privilege-elevation before" in content
        assert "Resource not previously accessed" in content

    def test_detail_404_for_missing_request(self, client: TestClient):
        """Accessing a non-existent request ID returns 404."""
        response = client.get("/detail/99999")
        assert response.status_code == 404

    def test_detail_shows_recommended_approver(
        self, client: TestClient, test_db_session: Session
    ):
        """The recommended approver is displayed on the detail page."""
        req = _create_request(
            test_db_session,
            recommended_approver="owner@company.com",
        )
        response = client.get(f"/detail/{req.id}")
        assert response.status_code == 200
        assert b"owner@company.com" in response.content


class TestApproveAction:
    """Tests for POST /detail/{request_id}/approve."""

    def test_approve_pending_request_redirects_and_updates_status(
        self, client: TestClient, test_db_session: Session
    ):
        """Approving a pending request changes its status to approved and redirects to queue."""
        req = _create_request(test_db_session, status=RequestStatus.PENDING_REVIEW)
        response = client.post(f"/detail/{req.id}/approve")
        assert response.status_code == 303
        assert response.headers["location"] == "/queue"

        # Verify status changed in DB
        test_db_session.refresh(req)
        assert req.status == RequestStatus.APPROVED

    def test_approve_non_pending_request_returns_400(
        self, client: TestClient, test_db_session: Session
    ):
        """Approving an already approved or rejected request returns 400."""
        req = _create_request(test_db_session, status=RequestStatus.APPROVED)
        response = client.post(f"/detail/{req.id}/approve")
        assert response.status_code == 400
        assert b"not pending review" in response.content.lower()

    def test_approve_nonexistent_request_returns_404(self, client: TestClient):
        """Approving a missing request returns 404."""
        response = client.post("/detail/99999/approve")
        assert response.status_code == 404


class TestRejectAction:
    """Tests for POST /detail/{request_id}/reject."""

    def test_reject_pending_request_redirects_and_updates_status(
        self, client: TestClient, test_db_session: Session
    ):
        """Rejecting a pending request changes its status to rejected and redirects to queue."""
        req = _create_request(test_db_session, status=RequestStatus.PENDING_REVIEW)
        response = client.post(f"/detail/{req.id}/reject")
        assert response.status_code == 303
        assert response.headers["location"] == "/queue"

        test_db_session.refresh(req)
        assert req.status == RequestStatus.REJECTED

    def test_reject_non_pending_request_returns_400(
        self, client: TestClient, test_db_session: Session
    ):
        """Rejecting an already approved or rejected request returns 400."""
        req = _create_request(test_db_session, status=RequestStatus.REJECTED)
        response = client.post(f"/detail/{req.id}/reject")
        assert response.status_code == 400

    def test_reject_nonexistent_request_returns_404(self, client: TestClient):
        """Rejecting a missing request returns 404."""
        response = client.post("/detail/99999/reject")
        assert response.status_code == 404


class TestOverrideAction:
    """Tests for POST /detail/{request_id}/override."""

    def test_override_pending_request_redirects_and_updates_classification(
        self, client: TestClient, test_db_session: Session
    ):
        """Override changes the classification and confidence, approves the request, and redirects."""
        req = _create_request(
            test_db_session,
            classification=RequestType.DATA_ACCESS,
            classification_confidence=0.9,
            status=RequestStatus.PENDING_REVIEW,
        )
        response = client.post(
            f"/detail/{req.id}/override",
            data={"classification": "system-access", "classification_confidence": 0.95},
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/queue"

        test_db_session.refresh(req)
        assert req.classification == RequestType.SYSTEM_ACCESS
        assert req.classification_confidence == 0.95
        assert req.status == RequestStatus.APPROVED

    def test_override_invalid_classification_returns_422(
        self, client: TestClient, test_db_session: Session
    ):
        """Providing an invalid classification enum value returns 422."""
        req = _create_request(test_db_session, status=RequestStatus.PENDING_REVIEW)
        response = client.post(
            f"/detail/{req.id}/override",
            data={"classification": "invalid-type", "classification_confidence": 0.5},
        )
        assert response.status_code == 422

    def test_override_non_pending_request_returns_400(
        self, client: TestClient, test_db_session: Session
    ):
        """Overriding a non-pending request returns 400."""
        req = _create_request(test_db_session, status=RequestStatus.AUTO_APPROVED)
        response = client.post(
            f"/detail/{req.id}/override",
            data={"classification": "data-access", "classification_confidence": 0.5},
        )
        assert response.status_code == 400

    def test_override_nonexistent_request_returns_404(self, client: TestClient):
        """Overriding a missing request returns 404."""
        response = client.post(
            "/detail/99999/override",
            data={"classification": "data-access", "classification_confidence": 0.5},
        )
        assert response.status_code == 404
