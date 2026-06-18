import pytest
from app.schemas import RoleMapping
from app.services.routing import route_request
from app.config import settings


class TestRouteRequest:
    """Tests for route_request service function."""

    @pytest.fixture
    def sample_role_mappings(self):
        return [
            RoleMapping(
                role_name="Finance Viewer",
                resource="dashboard",
                owner="finance@company.com",
                confidence=0.95,
            )
        ]

    def test_auto_approved_when_score_below_threshold_and_mappings_exist(
        self, sample_role_mappings
    ):
        """Low anomaly and confident mapping => auto_approved."""
        result = route_request(
            anomaly_score=0.2,
            role_mappings=sample_role_mappings,
        )
        assert result == "auto_approved"

    def test_pending_review_when_score_above_threshold(self, sample_role_mappings):
        """High anomaly even with mappings => pending_review."""
        result = route_request(
            anomaly_score=0.7,
            role_mappings=sample_role_mappings,
        )
        assert result == "pending_review"

    def test_pending_review_when_score_exactly_threshold(self, sample_role_mappings):
        """Score exactly equal to threshold (not <) => pending_review."""
        result = route_request(
            anomaly_score=settings.anomaly_threshold,
            role_mappings=sample_role_mappings,
        )
        assert result == "pending_review"

    def test_pending_review_when_no_role_mappings(self):
        """No mappings even with low score => pending_review."""
        result = route_request(
            anomaly_score=0.1,
            role_mappings=[],
        )
        assert result == "pending_review"

    def test_pending_review_when_high_score_and_no_mappings(self):
        """Both conditions fail => pending_review."""
        result = route_request(
            anomaly_score=0.9,
            role_mappings=[],
        )
        assert result == "pending_review"

    def test_custom_threshold_used_when_provided(self, sample_role_mappings):
        """If anomaly_threshold is explicitly passed, use it instead of the setting."""
        result = route_request(
            anomaly_score=0.4,
            role_mappings=sample_role_mappings,
            anomaly_threshold=0.5,
        )
        assert result == "auto_approved"

        result = route_request(
            anomaly_score=0.6,
            role_mappings=sample_role_mappings,
            anomaly_threshold=0.5,
        )
        assert result == "pending_review"

    def test_auto_approved_at_zero_score(self, sample_role_mappings):
        """Zero anomaly and mapping => auto_approved."""
        result = route_request(
            anomaly_score=0.0,
            role_mappings=sample_role_mappings,
        )
        assert result == "auto_approved"

    def test_pending_review_at_one_score_with_mappings(self, sample_role_mappings):
        """Max anomaly with mappings => pending_review."""
        result = route_request(
            anomaly_score=1.0,
            role_mappings=sample_role_mappings,
        )
        assert result == "pending_review"
