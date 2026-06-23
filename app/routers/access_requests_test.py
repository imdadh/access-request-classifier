import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, AccessRequest, Requester, RequestType, RequestStatus
from app.db.session import get_db
from app.main import app


@pytest.fixture
def test_db_session():
    """Create an in-memory SQLite database, create tables, yield a session, then drop.

    Uses StaticPool + check_same_thread=False so the single in-memory DB is shared
    with the TestClient's worker thread (FastAPI runs sync endpoints in a threadpool).
    Function-scoped for full per-test isolation.
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
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def seed_requester(test_db_session: Session):
    """Insert a sample requester for status-lookup tests."""
    requester = Requester(id="test_user", name="Test User", email="test@example.com")
    test_db_session.add(requester)
    test_db_session.commit()
    return requester


class TestCreateAccessRequest:
    """Tests for POST /access-requests."""

    def test_valid_intake_returns_201_and_matches_schema(self, client: TestClient):
        """A valid request should return 201 with a structured response."""
        payload = {
            "requester_id": "alice",
            "request_text": "I need access to the finance dashboard",
        }
        response = client.post("/access-requests", json=payload)
        assert response.status_code == 201
        data = response.json()
        # Verify required keys exist
        assert "id" in data
        assert data["requester_id"] == "alice"
        assert data["request_text"] == "I need access to the finance dashboard"
        assert "classification" in data
        assert "classification_confidence" in data
        assert "role_mappings" in data
        assert "anomaly_score" in data
        assert "status" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_missing_requester_id_returns_422(self, client: TestClient):
        """Omitting requester_id should yield a 422 error."""
        payload = {"request_text": "need access"}
        response = client.post("/access-requests", json=payload)
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        # FastAPI validation errors include loc and msg
        assert any("requester_id" in str(err.get("loc", [])) for err in data["detail"])

    def test_empty_requester_id_returns_422(self, client: TestClient):
        """An empty string for requester_id should yield a 422 error."""
        payload = {"requester_id": "", "request_text": "need access"}
        response = client.post("/access-requests", json=payload)
        assert response.status_code == 422

    def test_missing_request_text_returns_422(self, client: TestClient):
        """Omitting request_text should yield a 422 error."""
        payload = {"requester_id": "alice"}
        response = client.post("/access-requests", json=payload)
        assert response.status_code == 422
        data = response.json()
        assert any("request_text" in str(err.get("loc", [])) for err in data["detail"])

    def test_empty_request_text_returns_422(self, client: TestClient):
        """An empty string for request_text should yield a 422 error."""
        payload = {"requester_id": "alice", "request_text": ""}
        response = client.post("/access-requests", json=payload)
        assert response.status_code == 422

    def test_extra_fields_ignored(self, client: TestClient):
        """Additional fields in the payload should be ignored and not cause errors."""
        payload = {
            "requester_id": "bob",
            "request_text": "I need read access to prod DB",
            "unexpected_field": "should not break",
        }
        response = client.post("/access-requests", json=payload)
        assert response.status_code == 201

    def test_non_string_requester_id_returns_422(self, client: TestClient):
        """If requester_id is not a string, a 422 should be returned."""
        payload = {"requester_id": 123, "request_text": "need access"}
        response = client.post("/access-requests", json=payload)
        assert response.status_code == 422


class TestGetAccessRequest:
    """Tests for GET /access-requests/{request_id}."""

    def test_valid_id_returns_request(
        self, client: TestClient, test_db_session: Session, seed_requester: Requester
    ):
        """A known request ID should return the full request details."""
        # Insert a real AccessRequest into the test DB
        access_request = AccessRequest(
            requester_id="test_user",
            request_text="Need finance dashboard access",
            classification=RequestType.DATA_ACCESS,
            classification_confidence=0.95,
            anomaly_score=0.2,
            anomaly_factors="No prior requests",
            recommended_approver="alice@company.com",
            status=RequestStatus.PENDING_REVIEW,
        )
        test_db_session.add(access_request)
        test_db_session.commit()
        request_id = access_request.id

        response = client.get(f"/access-requests/{request_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == request_id
        assert data["requester_id"] == "test_user"
        assert data["request_text"] == "Need finance dashboard access"
        assert data["classification"] == "data-access"
        assert data["status"] == "pending_review"

    def test_nonexistent_id_returns_404(self, client: TestClient):
        """A request ID that does not exist should return 404."""
        response = client.get("/access-requests/99999")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_invalid_id_type_returns_422(self, client: TestClient):
        """A non-integer path parameter should result in a 422."""
        response = client.get("/access-requests/abc")
        # FastAPI automatically rejects non-integer path params with 422
        assert response.status_code == 422
