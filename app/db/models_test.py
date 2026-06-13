import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    Requester,
    Role,
    AccessRequest,
    Decision,
    RequestType,
    RequestStatus,
    DecisionAction,
)


@pytest.fixture(scope="module")
def db_session():
    """Create an in-memory SQLite database, create tables, yield a session, then drop everything."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


class TestRequester:
    def test_create_requester(self, db_session: Session):
        req = Requester(id="test_user", name="Test User", email="test@example.com")
        db_session.add(req)
        db_session.commit()
        assert req.id == "test_user"
        assert req.name == "Test User"
        assert req.email == "test@example.com"
        assert req.created_at is not None

    def test_requester_optional_email(self, db_session: Session):
        req = Requester(id="user2", name="No Email")
        db_session.add(req)
        db_session.commit()
        assert req.email is None

    def test_requester_unique_id(self, db_session: Session):
        req1 = Requester(id="dup", name="A")
        req2 = Requester(id="dup", name="B")
        db_session.add(req1)
        db_session.commit()
        db_session.add(req2)
        with pytest.raises(Exception):
            db_session.commit()
        db_session.rollback()


class TestRole:
    def test_create_role(self, db_session: Session):
        role = Role(
            name="test-role",
            resource="Some Resource",
            owner="owner@test.com",
            description="A test role",
        )
        db_session.add(role)
        db_session.commit()
        assert role.id is not None
        assert role.name == "test-role"

    def test_role_name_unique(self, db_session: Session):
        r1 = Role(name="unique", resource="A", owner="o@t.com")
        r2 = Role(name="unique", resource="B", owner="o@t.com")
        db_session.add(r1)
        db_session.commit()
        db_session.add(r2)
        with pytest.raises(Exception):
            db_session.commit()
        db_session.rollback()

    def test_role_optional_description(self, db_session: Session):
        role = Role(name="no-desc", resource="R", owner="o@t.com")
        db_session.add(role)
        db_session.commit()
        assert role.description is None


class TestAccessRequest:
    def test_create_access_request(self, db_session: Session):
        requester = Requester(id="ar_user", name="AR User")
        db_session.add(requester)
        db_session.flush()

        ar = AccessRequest(
            requester_id="ar_user",
            request_text="I need access",
            classification=RequestType.DATA_ACCESS,
            classification_confidence=0.95,
            anomaly_score=0.2,
            anomaly_factors=None,
            recommended_approver="approver@test.com",
            status=RequestStatus.PENDING_REVIEW,
        )
        db_session.add(ar)
        db_session.commit()

        assert ar.id is not None
        assert ar.classification == RequestType.DATA_ACCESS
        assert ar.status == RequestStatus.PENDING_REVIEW
        assert ar.created_at is not None
        assert ar.updated_at is not None
        assert ar.requester.id == "ar_user"

    def test_foreign_key_requester(self, db_session: Session):
        ar = AccessRequest(
            requester_id="nonexistent",
            request_text="test",
            classification=RequestType.SYSTEM_ACCESS,
            classification_confidence=0.5,
            anomaly_score=0.0,
            status=RequestStatus.PENDING_REVIEW,
        )
        db_session.add(ar)
        with pytest.raises(Exception):
            db_session.commit()
        db_session.rollback()

    def test_relationship_back_populates(self, db_session: Session):
        requester = Requester(id="rel_user", name="Rel")
        db_session.add(requester)
        db_session.flush()

        ar = AccessRequest(
            requester_id="rel_user",
            request_text="rel test",
            classification=RequestType.APP_ACCESS,
            classification_confidence=0.8,
            anomaly_score=0.1,
            status=RequestStatus.AUTO_APPROVED,
        )
        db_session.add(ar)
        db_session.commit()

        # Check reverse relationship
        assert len(requester.access_requests) == 1
        assert requester.access_requests[0].request_text == "rel test"
        assert ar.requester == requester


class TestDecision:
    def test_create_decision(self, db_session: Session):
        requester = Requester(id="dec_user", name="Dec")
        db_session.add(requester)
        db_session.flush()

        ar = AccessRequest(
            requester_id="dec_user",
            request_text="dec test",
            classification=RequestType.PRIVILEGE_ELEVATION,
            classification_confidence=0.9,
            anomaly_score=0.3,
            status=RequestStatus.PENDING_REVIEW,
        )
        db_session.add(ar)
        db_session.flush()

        dec = Decision(
            access_request_id=ar.id,
            actor="admin",
            action=DecisionAction.APPROVE,
            details="Looks fine",
        )
        db_session.add(dec)
        db_session.commit()

        assert dec.id is not None
        assert dec.action == DecisionAction.APPROVE
        assert dec.timestamp is not None
        assert dec.access_request.id == ar.id

    def test_decision_optional_details(self, db_session: Session):
        requester = Requester(id="dec2_user", name="Dec2")
        db_session.add(requester)
        db_session.flush()

        ar = AccessRequest(
            requester_id="dec2_user",
            request_text="no details",
            classification=RequestType.DATA_ACCESS,
            classification_confidence=1.0,
            anomaly_score=0.0,
            status=RequestStatus.AUTO_APPROVED,
        )
        db_session.add(ar)
        db_session.flush()

        dec = Decision(
            access_request_id=ar.id,
            actor="system",
            action=DecisionAction.APPROVE,
        )
        db_session.add(dec)
        db_session.commit()
        assert dec.details is None

    def test_decision_relationship(self, db_session: Session):
        requester = Requester(id="dec3_user", name="Dec3")
        db_session.add(requester)
        db_session.flush()

        ar = AccessRequest(
            requester_id="dec3_user",
            request_text="multi decisions",
            classification=RequestType.SYSTEM_ACCESS,
            classification_confidence=0.7,
            anomaly_score=0.6,
            status=RequestStatus.PENDING_REVIEW,
        )
        db_session.add(ar)
        db_session.flush()

        d1 = Decision(
            access_request_id=ar.id, actor="a1", action=DecisionAction.APPROVE
        )
        d2 = Decision(
            access_request_id=ar.id, actor="a2", action=DecisionAction.OVERRIDE
        )
        db_session.add_all([d1, d2])
        db_session.commit()

        assert len(ar.decisions) == 2
        assert ar.decisions[0].actor in ("a1", "a2")
        assert ar.decisions[1].actor in ("a1", "a2")


class TestEnumFields:
    def test_request_type_values(self):
        assert RequestType.DATA_ACCESS.value == "data-access"
        assert RequestType.SYSTEM_ACCESS.value == "system-access"
        assert RequestType.APP_ACCESS.value == "app-access"
        assert RequestType.PRIVILEGE_ELEVATION.value == "privilege-elevation"

    def test_request_status_values(self):
        assert RequestStatus.PENDING_REVIEW.value == "pending_review"
        assert RequestStatus.AUTO_APPROVED.value == "auto_approved"
        assert RequestStatus.APPROVED.value == "approved"
        assert RequestStatus.REJECTED.value == "rejected"

    def test_decision_action_values(self):
        assert DecisionAction.APPROVE.value == "approve"
        assert DecisionAction.REJECT.value == "reject"
        assert DecisionAction.OVERRIDE.value == "override"
