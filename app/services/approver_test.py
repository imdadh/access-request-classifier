from app.schemas import RoleMapping
from app.services.approver import resolve_approver
from app.config import settings


class TestResolveApprover:
    """Tests for resolve_approver service function."""

    def test_returns_owner_of_first_role_mapping(self):
        """Given non-empty role_mappings, return the owner of the highest-confidence one."""
        mappings = [
            RoleMapping(
                role_name="Finance Viewer",
                resource="dashboard",
                owner="finance@company.com",
                confidence=0.95,
            ),
            RoleMapping(
                role_name="DB Read",
                resource="database",
                owner="db@company.com",
                confidence=0.80,
            ),
        ]
        result = resolve_approver(mappings)
        assert result == "finance@company.com"

    def test_returns_default_reviewer_queue_when_empty(self):
        """Empty role_mappings returns the default reviewer queue from settings."""
        result = resolve_approver([])
        assert result == settings.default_reviewer_queue

    def test_does_not_mutate_input_list(self):
        """Ensure the input list is not modified."""
        mappings = [
            RoleMapping(
                role_name="Test Role",
                resource="test-resource",
                owner="owner@test.com",
                confidence=0.9,
            )
        ]
        original_len = len(mappings)
        _ = resolve_approver(mappings)
        assert len(mappings) == original_len

    def test_single_mapping_returns_its_owner(self):
        """A single mapping returns its owner."""
        mappings = [
            RoleMapping(
                role_name="Sole Role",
                resource="sole-resource",
                owner="sole@company.com",
                confidence=0.5,
            )
        ]
        assert resolve_approver(mappings) == "sole@company.com"

    def test_handles_low_confidence_mapping(self):
        """Even low-confidence mappings still return their owner if they're the first."""
        mappings = [
            RoleMapping(
                role_name="Low",
                resource="low-res",
                owner="low@company.com",
                confidence=0.1,
            )
        ]
        assert resolve_approver(mappings) == "low@company.com"
