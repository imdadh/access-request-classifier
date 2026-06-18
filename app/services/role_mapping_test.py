import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, Role, RequestType
from app.schemas import RoleMapping
from app.services.role_mapping import map_roles


@pytest.fixture(scope="module")
def test_db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def seed_roles(test_db_session: Session):
    """Insert a minimal set of roles before each test."""
    roles = [
        Role(
            name="Finance Dashboard Viewer",
            resource="finance-reporting-dashboard",
            owner="finance-owner@company.com",
        ),
        Role(
            name="Prod DB Read Only",
            resource="production-database",
            owner="db-owner@company.com",
        ),
        Role(
            name="AWS Admin",
            resource="aws-account-prod",
            owner="cloud-owner@company.com",
        ),
        Role(
            name="HR System Access", resource="hr-portal", owner="hr-owner@company.com"
        ),
    ]
    for r in roles:
        test_db_session.add(r)
    test_db_session.commit()


class TestMapRoles:
    """Tests for map_roles service function."""

    def test_returns_sorted_list_of_role_mappings(self, test_db_session: Session):
        """A request matching a role should return a non-empty sorted list."""
        result = map_roles(
            db=test_db_session,
            request_text="I need to view the finance reporting dashboard",
            request_type=RequestType.DATA_ACCESS,
        )
        assert len(result) > 0
        # Highest confidence first
        for i in range(len(result) - 1):
            assert result[i].confidence >= result[i + 1].confidence
        # All returned objects are RoleMapping instances
        for rm in result:
            assert isinstance(rm, RoleMapping)

    def test_returns_multiple_matches_when_relevant(self, test_db_session: Session):
        """A generic request may match multiple roles with varying confidence."""
        result = map_roles(
            db=test_db_session,
            request_text="I need access to the database for reporting",
            request_type=RequestType.DATA_ACCESS,
        )
        # Should at least match Prod DB Read Only and possibly Finance Dashboard
        assert len(result) >= 1
        # Verify tokens like "database" are present
        assert any(
            "database" in rm.resource or "database" in rm.role_name.lower()
            for rm in result
        )

    def test_returns_empty_list_when_no_role_matches(self, test_db_session: Session):
        """A request with no overlap should produce an empty list."""
        result = map_roles(
            db=test_db_session,
            request_text="I need access to the staff cafeteria booking system",
            request_type=RequestType.SYSTEM_ACCESS,
        )
        assert result == []

    def test_returns_empty_list_when_no_roles_exist(self, test_db_session: Session):
        """Empty role table returns empty list."""
        # Clear roles for this test
        test_db_session.query(Role).delete()
        test_db_session.commit()
        result = map_roles(
            db=test_db_session,
            request_text="I need the finance dashboard",
            request_type=RequestType.DATA_ACCESS,
        )
        assert result == []

    def test_empty_request_text_returns_empty_list(self, test_db_session: Session):
        """A request with no meaningful tokens returns empty."""
        result = map_roles(
            db=test_db_session,
            request_text="a an the",
            request_type=RequestType.DATA_ACCESS,
        )
        assert result == []

    def test_confidence_scores_are_between_zero_and_one(self, test_db_session: Session):
        """All returned confidence values must be in [0,1]."""
        result = map_roles(
            db=test_db_session,
            request_text="access to production database read only",
            request_type=RequestType.DATA_ACCESS,
        )
        for rm in result:
            assert 0.0 <= rm.confidence <= 1.0

    def test_top_result_has_highest_confidence(self, test_db_session: Session):
        """The first element has the highest confidence."""
        result = map_roles(
            db=test_db_session,
            request_text="finance dashboard reporting",
            request_type=RequestType.DATA_ACCESS,
        )
        if result:
            top = result[0].confidence
            for rm in result[1:]:
                assert top >= rm.confidence
