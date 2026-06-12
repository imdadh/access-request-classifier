import logging

from sqlalchemy.orm import Session

from app.db.models import Requester, Role

logger = logging.getLogger(__name__)

# Synthetic role catalog: each entry defines a role name, the resource it grants,
# the resource owner, and a brief description.
SEED_ROLES = [
    {
        "name": "finance-report-reader",
        "resource": "Finance Reporting Dashboard",
        "owner": "alice@company.com",
        "description": "Read-only access to finance reports for Q3 close and quarterly analysis.",
    },
    {
        "name": "finance-report-admin",
        "resource": "Finance Reporting Dashboard",
        "owner": "alice@company.com",
        "description": "Administrative access to manage finance report configurations and user permissions.",
    },
    {
        "name": "prod-db-reader",
        "resource": "Production Database",
        "owner": "bob@company.com",
        "description": "Read-only queries on the production database for monitoring and reporting.",
    },
    {
        "name": "prod-db-writer",
        "resource": "Production Database",
        "owner": "bob@company.com",
        "description": "Write access to the production database for data corrections and updates.",
    },
    {
        "name": "aws-console-readonly",
        "resource": "AWS Console",
        "owner": "charlie@company.com",
        "description": "Read-only access to AWS resources via the console (CloudWatch, S3, etc.).",
    },
    {
        "name": "aws-console-admin",
        "resource": "AWS Console",
        "owner": "charlie@company.com",
        "description": "Full administrative access to AWS console and CLI.",
    },
    {
        "name": "admin-panel-user",
        "resource": "Internal Admin Panel",
        "owner": "dave@company.com",
        "description": "Standard user access to the internal admin panel for managing daily operations.",
    },
    {
        "name": "admin-panel-superuser",
        "resource": "Internal Admin Panel",
        "owner": "dave@company.com",
        "description": "Superuser access with the ability to modify system configurations and user roles.",
    },
    {
        "name": "hr-dashboard-reader",
        "resource": "HR Reporting Dashboard",
        "owner": "eve@company.com",
        "description": "Read-only access to HR reports, headcount, and payroll data.",
    },
    {
        "name": "engineering-git-admin",
        "resource": "Engineering Git Repositories",
        "owner": "frank@company.com",
        "description": "Administrative access to manage repositories, branches, and CI/CD pipelines.",
    },
]

# Sample requesters for initial development use.
SEED_REQUESTERS = [
    {"id": "alice", "name": "Alice Smith", "email": "alice@company.com"},
    {"id": "bob", "name": "Bob Jones", "email": "bob@company.com"},
    {"id": "charlie", "name": "Charlie Lee", "email": "charlie@company.com"},
    {"id": "dave", "name": "Dave Patel", "email": "dave@company.com"},
    {"id": "eve", "name": "Eve Martin", "email": "eve@company.com"},
    {"id": "frank", "name": "Frank Zhang", "email": "frank@company.com"},
]


def seed_database(db: Session) -> None:
    """Load synthetic role catalog and sample requesters into the database.

    This function is idempotent: it will only insert rows if the corresponding
    tables are empty. This ensures repeated calls (e.g., on app restart) do not
    create duplicates.
    """
    _seed_roles(db)
    _seed_requesters(db)
    db.commit()
    logger.info("Database seeded with synthetic role catalog and sample requesters.")


def _seed_roles(db: Session) -> None:
    existing_count = db.query(Role).count()
    if existing_count > 0:
        logger.info(
            "Roles table already has %d rows; skipping role seeding.", existing_count
        )
        return

    roles = [Role(**r) for r in SEED_ROLES]
    db.add_all(roles)
    logger.info("Inserted %d synthetic roles.", len(roles))


def _seed_requesters(db: Session) -> None:
    existing_count = db.query(Requester).count()
    if existing_count > 0:
        logger.info(
            "Requesters table already has %d rows; skipping requester seeding.",
            existing_count,
        )
        return

    requesters = [Requester(**r) for r in SEED_REQUESTERS]
    db.add_all(requesters)
    logger.info("Inserted %d sample requesters.", len(requesters))
