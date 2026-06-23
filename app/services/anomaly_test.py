import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base, AccessRequest, RequestType, RequestStatus
from app.services.anomaly import compute_anomaly_score


@pytest.fixture(scope="module")
def test_db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


class TestComputeAnomalyScore:
    """Tests for compute_anomaly_score service function."""

    def test_cold_start_with_no_history(self, test_db_session: Session):
        """A requester with zero prior accepted requests gets cold-start score."""
        score, factors = compute_anomaly_score(
            db=test_db_session,
            requester_id="new_user",
            request_type=RequestType.DATA_ACCESS,
        )
        assert score == settings.cold_start_anomaly_score
        assert len(factors) == 1
        assert "insufficient history" in factors[0]

    def test_cold_start_with_below_min_history(self, test_db_session: Session):
        """A requester with history count < cold_start_min_history gets cold-start score."""
        # Insert one accepted request (min is 2)
        req = AccessRequest(
            requester_id="partial_user",
            request_text="test",
            classification=RequestType.DATA_ACCESS,
            classification_confidence=0.9,
            anomaly_score=0.2,
            status=RequestStatus.AUTO_APPROVED,
        )
        test_db_session.add(req)
        test_db_session.commit()

        score, factors = compute_anomaly_score(
            db=test_db_session,
            requester_id="partial_user",
            request_type=RequestType.SYSTEM_ACCESS,
        )
        assert score == settings.cold_start_anomaly_score
        assert "1 prior accepted request" in factors[0] or "1 prior" in factors[0]

    def test_warm_start_low_anomaly(self, test_db_session: Session):
        """Many prior requests of same type yield low anomaly."""
        requester_id = "consistent_user"
        # Insert several accepted requests all of type DATA_ACCESS
        for _ in range(5):
            req = AccessRequest(
                requester_id=requester_id,
                request_text="need dashboard",
                classification=RequestType.DATA_ACCESS,
                classification_confidence=0.9,
                anomaly_score=0.1,
                status=RequestStatus.AUTO_APPROVED,
            )
            test_db_session.add(req)
        test_db_session.commit()

        score, factors = compute_anomaly_score(
            db=test_db_session,
            requester_id=requester_id,
            request_type=RequestType.DATA_ACCESS,
        )
        # With 5/5 same type, type_anomaly = 0.0, so overall should be low
        assert score < 0.3
        assert len(factors) >= 1

    def test_warm_start_high_anomaly_different_type(self, test_db_session: Session):
        """New type with many prior of different type yields high anomaly."""
        requester_id = "switch_user"
        for _ in range(5):
            req = AccessRequest(
                requester_id=requester_id,
                request_text="need dashboard",
                classification=RequestType.DATA_ACCESS,
                classification_confidence=0.9,
                anomaly_score=0.1,
                status=RequestStatus.APPROVED,
            )
            test_db_session.add(req)
        test_db_session.commit()

        score, factors = compute_anomaly_score(
            db=test_db_session,
            requester_id=requester_id,
            request_type=RequestType.PRIVILEGE_ELEVATION,
        )
        # 0/5 same type => type_anomaly = 1.0
        assert score == pytest.approx(1.0, abs=0.01)
        assert any("0 of 5" in f or "0 of 5" in f for f in factors)

    def test_resource_anomaly_included(self, test_db_session: Session):
        """When resource is provided, it adds a factor and may increase score."""
        requester_id = "resource_user"
        # Two prior accepted requests mentioning "dashboard" (not "database"), so the
        # requester is past cold-start and the resource "database" is fully novel.
        for _ in range(2):
            req = AccessRequest(
                requester_id=requester_id,
                request_text="need dashboard access",
                classification=RequestType.DATA_ACCESS,
                classification_confidence=0.9,
                anomaly_score=0.1,
                status=RequestStatus.AUTO_APPROVED,
            )
            test_db_session.add(req)
        test_db_session.commit()

        score, factors = compute_anomaly_score(
            db=test_db_session,
            requester_id=requester_id,
            request_type=RequestType.DATA_ACCESS,
            resource="database",
        )
        # type_anomaly = 0.0 (same type), resource_anomaly = 1.0 (database not in prior text)
        assert score == pytest.approx(1.0, abs=0.01)
        assert any("resource deviation" in f for f in factors)

    def test_factors_persisted_when_request_id_given(self, test_db_session: Session):
        """If request_id is provided, anomaly_factors field is updated."""
        # Create a request record without anomaly_factors
        req = AccessRequest(
            requester_id="persist_test",
            request_text="test",
            classification=RequestType.DATA_ACCESS,
            classification_confidence=0.9,
            anomaly_score=0.0,
            status=RequestStatus.PENDING_REVIEW,
        )
        test_db_session.add(req)
        test_db_session.commit()
        request_id = req.id

        score, factors = compute_anomaly_score(
            db=test_db_session,
            requester_id="persist_test",
            request_type=RequestType.DATA_ACCESS,
            request_id=request_id,
        )
        # Refresh and check
        test_db_session.refresh(req)
        assert req.anomaly_factors is not None
        persisted = json.loads(req.anomaly_factors)
        assert len(persisted) > 0
        assert persisted[0] == factors[0]

    def test_only_accepted_requests_considered(self, test_db_session: Session):
        """Requests with status PENDING_REVIEW or REJECTED are excluded."""
        requester_id = "mix_user"
        # Add one accepted and one pending
        acc = AccessRequest(
            requester_id=requester_id,
            request_text="accepted",
            classification=RequestType.DATA_ACCESS,
            classification_confidence=0.9,
            anomaly_score=0.1,
            status=RequestStatus.AUTO_APPROVED,
        )
        pen = AccessRequest(
            requester_id=requester_id,
            request_text="pending",
            classification=RequestType.SYSTEM_ACCESS,
            classification_confidence=0.9,
            anomaly_score=0.5,
            status=RequestStatus.PENDING_REVIEW,
        )
        test_db_session.add_all([acc, pen])
        test_db_session.commit()

        score, factors = compute_anomaly_score(
            db=test_db_session,
            requester_id=requester_id,
            request_type=RequestType.DATA_ACCESS,
        )
        # Only 1 accepted request, so history=1 -> cold-start
        assert score == settings.cold_start_anomaly_score
