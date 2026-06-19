import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db.models import Base
from app.db.session import get_db
from app.main import app


class MockLLMClient:
    """A deterministic mock LLM client for offline testing.

    Returns a fixed classification result.  Test cases that need custom
    responses can override attributes on the instance before calling.
    """

    def __init__(self):
        self.last_request: str | None = None
        self.classification_result: dict = {
            "type": "data-access",
            "confidence": 0.95,
            "resource": "finance-dashboard",
            "role": "finance-analyst",
        }

    def classify(self, text: str) -> dict:
        self.last_request = text
        return self.classification_result


@pytest.fixture(scope="module")
def test_db_session():
    """Provide a clean in-memory SQLite database for a module of tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def mocked_llm_client() -> MockLLMClient:
    """Return a fresh MockLLMClient instance per test function."""
    return MockLLMClient()


@pytest.fixture
def test_client(test_db_session):
    """Return a FastAPI TestClient that uses the test database."""

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
