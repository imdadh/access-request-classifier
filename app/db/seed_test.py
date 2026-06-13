import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, Requester, Role
from app.db.seed import seed_database, SEED_ROLES, SEED_REQUESTERS


@pytest.fixture(scope="module")
def db_session():
    """Create an in-memory SQLite database, create tables, yield a session, then drop."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


class TestSeedDatabase:
    def test_seed_populates_tables(self, db_session: Session):
        """Seed should insert all roles and requesters when tables are empty."""
        seed_database(db_session)

        roles = db_session.query(Role).all()
        requesters = db_session.query(Requester).all()

        assert len(roles) == len(SEED_ROLES)
        assert len(requesters) == len(SEED_REQUESTERS)

    def test_seed_idempotent(self, db_session: Session):
        """Calling seed twice should not duplicate rows."""
        seed_database(db_session)
        seed_database(db_session)

        roles = db_session.query(Role).all()
        requesters = db_session.query(Requester).all()

        assert len(roles) == len(SEED_ROLES)
        assert len(requesters) == len(SEED_REQUESTERS)

    def test_seed_role_data(self, db_session: Session):
        """Verify specific role attributes from the seed data."""
        seed_database(db_session)

        role = db_session.query(Role).filter_by(name="finance-report-reader").one()
        assert role.resource == "Finance Reporting Dashboard"
        assert role.owner == "alice@company.com"
        assert role.description is not None

        role = db_session.query(Role).filter_by(name="engineering-git-admin").one()
        assert role.resource == "Engineering Git Repositories"
        assert role.owner == "frank@company.com"

    def test_seed_requester_data(self, db_session: Session):
        """Verify specific requester attributes."""
        seed_database(db_session)

        req = db_session.query(Requester).filter_by(id="alice").one()
        assert req.name == "Alice Smith"
        assert req.email == "alice@company.com"

        req = db_session.query(Requester).filter_by(id="frank").one()
        assert req.name == "Frank Zhang"
        assert req.email == "frank@company.com"

    def test_seed_optional_requester_email(self, db_session: Session):
        """All sample requesters have an email; but model allows None."""
        seed_database(db_session)
        for req in db_session.query(Requester).all():
            assert req.email is not None

    def test_seed_all_role_names_present(self, db_session: Session):
        """All expected role names from SEED_ROLES should exist."""
        seed_database(db_session)
        stored_names = {r.name for r in db_session.query(Role).all()}
        expected_names = {r["name"] for r in SEED_ROLES}
        assert stored_names == expected_names

    def test_seed_all_requester_ids_present(self, db_session: Session):
        """All expected requester IDs from SEED_REQUESTERS should exist."""
        seed_database(db_session)
        stored_ids = {r.id for r in db_session.query(Requester).all()}
        expected_ids = {r["id"] for r in SEED_REQUESTERS}
        assert stored_ids == expected_ids
