"""
Unit tests for Pydantic models — validates edge cases in validators.
"""
import pytest
from app.models.incident import FileReference, TriageVerdict, ParsedIncident


class TestFileReference:
    """Tests for FileReference model"""

    def test_file_reference_valid(self):
        """Valid file reference creation"""
        ref = FileReference(
            file_path="src/core/orders.js",
            relevance_score=0.85,
            reason="Contains order processing logic"
        )
        assert ref.file_path == "src/core/orders.js"
        assert ref.relevance_score == 0.85
        assert ref.reason == "Contains order processing logic"

    def test_file_reference_score_clamp_high(self):
        """Relevance score must be <= 1.0"""
        with pytest.raises(ValueError):
            FileReference(
                file_path="x.js",
                relevance_score=1.5,
                reason="test"
            )

    def test_file_reference_score_clamp_low(self):
        """Relevance score must be >= 0.0"""
        with pytest.raises(ValueError):
            FileReference(
                file_path="x.js",
                relevance_score=-0.1,
                reason="test"
            )

    def test_file_reference_score_boundary_valid(self):
        """Boundary values 0.0 and 1.0 are valid"""
        ref1 = FileReference(file_path="a.js", relevance_score=0.0, reason="low")
        assert ref1.relevance_score == 0.0

        ref2 = FileReference(file_path="b.js", relevance_score=1.0, reason="high")
        assert ref2.relevance_score == 1.0


class TestTriageVerdict:
    """Tests for TriageVerdict model"""

    def test_triage_verdict_valid_high_confidence(self):
        """Valid P1 verdict with high confidence"""
        verdict = TriageVerdict(
            severity="P1",
            severity_reasoning="Complete system outage",
            confidence=0.95,
            root_cause_hypothesis="Database connection lost"
        )
        assert verdict.severity == "P1"
        assert verdict.confidence == 0.95
        assert verdict.needs_human_review is False

    def test_triage_verdict_p1_low_confidence_degrades(self):
        """P1 with <0.5 confidence should degrade to P2"""
        verdict = TriageVerdict(
            severity="P1",
            severity_reasoning="bad",
            confidence=0.3,
            root_cause_hypothesis="unknown"
        )
        assert verdict.severity == "P2"
        assert verdict.needs_human_review is True

    def test_triage_verdict_low_confidence_requires_review(self):
        """P3 with low confidence (<0.5) requires human review"""
        verdict = TriageVerdict(
            severity="P3",
            severity_reasoning="minor issue",
            confidence=0.4,
            root_cause_hypothesis="cache miss"
        )
        assert verdict.needs_human_review is True

    def test_triage_verdict_medium_confidence_high_severity(self):
        """P2 with medium confidence doesn't auto-degrade"""
        verdict = TriageVerdict(
            severity="P2",
            severity_reasoning="API timeout",
            confidence=0.65,
            root_cause_hypothesis="slow query"
        )
        assert verdict.severity == "P2"
        assert verdict.needs_human_review is False

    def test_triage_verdict_invalid_severity(self):
        """Invalid severity level should raise error"""
        with pytest.raises(ValueError):
            TriageVerdict(
                severity="P5",
                severity_reasoning="invalid",
                confidence=0.8,
                root_cause_hypothesis="test"
            )

    def test_triage_verdict_confidence_bounds(self):
        """Confidence must be between 0 and 1"""
        with pytest.raises(ValueError):
            TriageVerdict(
                severity="P1",
                severity_reasoning="test",
                confidence=1.5,
                root_cause_hypothesis="test"
            )


class TestParsedIncident:
    """Tests for ParsedIncident model"""

    def test_parsed_incident_minimal(self):
        """Create incident with only required fields"""
        parsed = ParsedIncident(
            title="Test Incident",
            description="Test description"
        )
        assert parsed.title == "Test Incident"
        assert parsed.description == "Test description"
        assert parsed.information_sufficient is True
        assert parsed.symptoms == []
        assert parsed.affected_areas == []

    def test_parsed_incident_with_symptoms(self):
        """Incident with symptoms"""
        parsed = ParsedIncident(
            title="API Error",
            description="500 errors",
            symptoms=["High latency", "Service timeout"]
        )
        assert parsed.symptoms == ["High latency", "Service timeout"]

    def test_parsed_incident_insufficient_info(self):
        """Short description marks as insufficient"""
        parsed = ParsedIncident(
            title="Bug",
            description="Broken"
        )
        assert parsed.information_sufficient is False

    def test_parsed_incident_with_affected_areas(self):
        """Incident with affected areas"""
        parsed = ParsedIncident(
            title="Checkout Issue",
            description="Stripe payment failing",
            affected_areas=["payments", "checkout"]
        )
        assert parsed.affected_areas == ["payments", "checkout"]

    def test_parsed_incident_defaults(self):
        """Verify all defaults are set"""
        parsed = ParsedIncident(
            title="Test",
            description="This is a detailed description of a production issue"
        )
        assert parsed.information_sufficient is True
        assert parsed.symptoms == []
        assert parsed.affected_areas == []
        assert parsed.confidence_score >= 0.0
        assert parsed.confidence_score <= 1.0

    def test_parsed_incident_with_all_fields(self):
        """Create incident with all fields"""
        parsed = ParsedIncident(
            title="Payment Processing Failure",
            description="Critical issue affecting checkout",
            symptoms=["500 errors", "Payment declined"],
            affected_areas=["payments", "checkout", "stripe"],
            estimated_impact="500 transactions failed",
            confidence_score=0.92
        )
        assert parsed.confidence_score == 0.92
        assert len(parsed.symptoms) == 2
        assert len(parsed.affected_areas) == 3
