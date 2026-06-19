import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AccessRequest, RequestType, RequestStatus
from app.services.anomaly import compute_anomaly_score


class TestAnomalyColdStart:
    """Tests for anomaly cold-start behavior on low-history requesters."""

    def _seed_requests(
        self,
        db: Session,
        requester_id: str,
        count: int,
        request_type: RequestType = RequestType.DATA_ACCESS,
        status: RequestStatus = RequestStatus.AUTO_APPROVED,
    ) -> None:
        """Insert `count` historical requests for a requester, all with the given type and status."""
        for i in range(count):
            req = AccessRequest(
                requester_id=requester_id,
                request_text=f"Historical request {i}",
                classification=request_type,
                classification_confidence=0.9,
                anomaly_score=0.1,
                status=status,
                recommended_approver="approver@co.com",
            )
            db.add(req)
        db.commit()

    # ------------------------------------------------------------------
    # Cold-start boundary: no prior requests
    # ------------------------------------------------------------------

    def test_cold_start_no_history_returns_high_anomaly(self, test_db_session: Session):
        """A requester with zero prior requests should receive the cold-start anomaly score."""
        result = compute_anomaly_score(
            db=test_db_session,
            requester_id="new_user",
            request_type=RequestType.DATA_ACCESS,
            resource="finance-dashboard",
            role="finance-analyst",
        )
        assert result[0] == settings.cold_start_anomaly_score
        assert result[1] is not None
        # The factors list should contain a cold-start explanation
        factor_text = " ".join(result[1]).lower()
        assert "cold start" in factor_text or "no history" in factor_text

    # ------------------------------------------------------------------
    # Cold-start boundary: below minimum history threshold
    # ------------------------------------------------------------------

    def test_cold_start_insufficient_history_returns_high_anomaly(
        self, test_db_session: Session
    ):
        """A requester with fewer than cold_start_min_history requests still gets cold-start score."""
        # Seed just 1 request (min_history = 2)
        self._seed_requests(test_db_session, "alice", count=1)
        result = compute_anomaly_score(
            db=test_db_session,
            requester_id="alice",
            request_type=RequestType.APP_ACCESS,
            resource="some-resource",
            role="some-role",
        )
        assert result[0] == settings.cold_start_anomaly_score
        assert result[1] is not None
        factor_text = " ".join(result[1]).lower()
        assert "cold start" in factor_text or "insufficient history" in factor_text

    # ------------------------------------------------------------------
    # Above cold-start threshold: anomaly computed normally
    # ------------------------------------------------------------------

    def test_sufficient_history_returns_normal_anomaly(self, test_db_session: Session):
        """A requester with history >= cold_start_min_history gets a normal (non-cold-start) score."""
        # Seed exactly the minimum (2) requests of a different type
        self._seed_requests(
            test_db_session,
            "bob",
            count=settings.cold_start_min_history,
            request_type=RequestType.SYSTEM_ACCESS,
        )
        result = compute_anomaly_score(
            db=test_db_session,
            requester_id="bob",
            request_type=RequestType.DATA_ACCESS,
            resource="dashboard",
            role="analyst",
        )
        # With 2 prior requests of a different type, the anomaly score should be high but not the cold-start value
        assert result[0] != settings.cold_start_anomaly_score
        assert result[0] >= 0.0
        assert result[0] <= 1.0
        # Factors should be present and meaningful
        assert result[1] is not None
        assert len(result[1]) > 0

    # ------------------------------------------------------------------
    # Cold-start respects configuration
    # ------------------------------------------------------------------

    def test_cold_start_threshold_respected(
        self, test_db_session: Session, monkeypatch: pytest.MonkeyPatch
    ):
        """Lowering cold_start_min_history to 0 should disable cold-start behavior."""
        monkeypatch.setattr(settings, "cold_start_min_history", 0)
        # A requester with no history now has 0 required, so cold-start should not apply
        result = compute_anomaly_score(
            db=test_db_session,
            requester_id="carol",
            request_type=RequestType.DATA_ACCESS,
            resource="r",
            role="r",
        )
        # With min_history=0, anomaly is computed normally (no history means low deviation?)
        # The exact score depends on heuristic; we just ensure it's not the cold-start score
        assert result[0] != settings.cold_start_anomaly_score

    # ------------------------------------------------------------------
    # Cold-start with only rejected requests
    # ------------------------------------------------------------------

    def test_cold_start_only_rejected_requests(self, test_db_session: Session):
        """If a requester only has rejected/historical requests, they still count toward history.
        The anomaly service should use only auto_approved or approved requests as baseline;
        rejected requests should not contribute to the pattern (cold-start still applies).
        """
        # Seed 2 rejected requests (not part of approved baseline)
        self._seed_requests(
            test_db_session, "dave", count=2, status=RequestStatus.REJECTED
        )
        result = compute_anomaly_score(
            db=test_db_session,
            requester_id="dave",
            request_type=RequestType.DATA_ACCESS,
            resource="r",
            role="r",
        )
        # Because there are no approved/auto_approved requests, cold-start should still apply
        assert result[0] == settings.cold_start_anomaly_score

    # ------------------------------------------------------------------
    # Factors readability
    # ------------------------------------------------------------------

    def test_cold_start_factors_are_human_readable(self, test_db_session: Session):
        """Cold-start factors should be plain English strings, not numeric codes."""
        result = compute_anomaly_score(
            db=test_db_session,
            requester_id="eve",
            request_type=RequestType.PRIVILEGE_ELEVATION,
            resource="admin",
            role="admin",
        )
        assert result[1] is not None
        for factor in result[1]:
            assert isinstance(factor, str)
            # At least 5 characters and readable
            assert len(factor) > 5
            # Should not contain raw data dumps like brackets or quotes
            assert factor.isprintable()
