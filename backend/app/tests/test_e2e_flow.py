"""
Integration test: E2E incident analysis flow.
Tests the full orchestrator pipeline with mocked LLM and service responses.
"""
import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from app.models.incident import ParsedIncident, TriageVerdict, FileReference
from app.orchestrator import IncidentOrchestrator


@pytest.fixture
def mock_llm():
    """Mock LLM client"""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_services():
    """Mock external services"""
    return {
        "jira": AsyncMock(),
        "slack": AsyncMock(),
        "chroma": Mock()
    }


@pytest.fixture
def orchestrator(mock_llm, mock_services):
    """Create orchestrator with mocked dependencies"""
    return IncidentOrchestrator(
        llm_client=mock_llm,
        jira_client=mock_services["jira"],
        slack_client=mock_services["slack"],
        chroma_client=mock_services["chroma"]
    )


@pytest.mark.asyncio
async def test_e2e_incident_triage_and_ticket_creation(orchestrator, mock_llm, mock_services):
    """
    E2E Test: Parse incident -> Triage -> Create ticket -> Notify
    """
    # Setup
    incident_id = "test_incident_001"
    incident_title = "Checkout 500 Error"
    incident_description = "All payment attempts failing with 500 error"

    initial_state = {
        "id": incident_id,
        "title": incident_title,
        "description": incident_description,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }

    # Mock LLM responses
    mock_llm.parse_incident.return_value = ParsedIncident(
        title=incident_title,
        description=incident_description,
        symptoms=["500 errors", "Payment processing failure"],
        affected_areas=["payments", "checkout"],
        information_sufficient=True
    )

    mock_llm.triage.return_value = TriageVerdict(
        severity="P1",
        severity_reasoning="Complete checkout failure, revenue impact",
        confidence=0.94,
        root_cause_hypothesis="Stripe API key invalid or expired"
    )

    mock_llm.find_relevant_files.return_value = [
        FileReference(
            file_path="src/plugins/payments-stripe/checkout.js",
            relevance_score=0.97,
            reason="Core payment processing logic"
        ),
        FileReference(
            file_path="src/core/orders/processOrder.js",
            relevance_score=0.82,
            reason="Order processing flow"
        )
    ]

    # Mock service responses
    mock_services["jira"].create_issue.return_value = {
        "id": "JIRA-100",
        "key": "JIRA-100",
        "url": "http://jira-mock:8080/browse/JIRA-100"
    }

    mock_services["slack"].post_message.return_value = {
        "ok": True,
        "ts": "1234567890.123456"
    }

    # Execute orchestrator
    result = await orchestrator.process_incident(initial_state)

    # Assertions
    assert result is not None
    assert result["status"] == "completed"
    assert result["ticket_id"] == "JIRA-100"
    assert result["notifications_sent"] == ["slack", "jira"]

    # Verify LLM was called with correct input
    mock_llm.parse_incident.assert_called_once()
    mock_llm.triage.assert_called_once()
    mock_llm.find_relevant_files.assert_called_once()

    # Verify services were called
    mock_services["jira"].create_issue.assert_called_once()
    mock_services["slack"].post_message.assert_called_once()

    # Verify verdict
    assert result["triage_verdict"]["severity"] == "P1"
    assert result["triage_verdict"]["confidence"] == 0.94
    assert len(result["relevant_files"]) == 2


@pytest.mark.asyncio
async def test_e2e_low_confidence_incident_requires_review(orchestrator, mock_llm, mock_services):
    """
    Test: Low confidence verdict triggers human review flag
    """
    incident_id = "test_incident_002"

    initial_state = {
        "id": incident_id,
        "title": "Intermittent API Timeout",
        "description": "Sometimes requests timeout",
        "status": "pending"
    }

    # Mock LLM with low confidence
    mock_llm.parse_incident.return_value = ParsedIncident(
        title="Intermittent API Timeout",
        description="Sometimes requests timeout",
        information_sufficient=False
    )

    mock_llm.triage.return_value = TriageVerdict(
        severity="P3",
        severity_reasoning="Might be network issue",
        confidence=0.35,
        root_cause_hypothesis="Unknown - needs investigation"
    )

    # Execute
    result = await orchestrator.process_incident(initial_state)

    # Assertions
    assert result["triage_verdict"]["needs_human_review"] is True
    assert result["status"] == "pending_review"
    # Ticket may still be created but marked for review
    mock_services["jira"].create_issue.assert_called_once()


@pytest.mark.asyncio
async def test_e2e_incident_with_relevant_files(orchestrator, mock_llm, mock_services):
    """
    Test: Relevant files are identified and included in ticket
    """
    initial_state = {
        "id": "test_incident_003",
        "title": "Search Results Empty",
        "description": "Product search returns no results after deployment",
        "status": "pending"
    }

    # Mock responses with file identification
    mock_llm.parse_incident.return_value = ParsedIncident(
        title="Search Results Empty",
        description="Product search returns no results after deployment",
        symptoms=["No search results"],
        affected_areas=["search", "elasticsearch"]
    )

    mock_llm.triage.return_value = TriageVerdict(
        severity="P2",
        severity_reasoning="Major feature broken, affected all users",
        confidence=0.90,
        root_cause_hypothesis="Elasticsearch connection lost"
    )

    relevant_files = [
        FileReference(
            file_path="src/plugins/search-elasticsearch/client.js",
            relevance_score=0.96,
            reason="Elasticsearch connection management"
        ),
        FileReference(
            file_path="src/plugins/search-elasticsearch/config.js",
            relevance_score=0.88,
            reason="Connection configuration"
        ),
        FileReference(
            file_path="src/api/graphql/queries/searchProducts.graphql",
            relevance_score=0.75,
            reason="Search API schema"
        )
    ]

    mock_llm.find_relevant_files.return_value = relevant_files
    mock_services["jira"].create_issue.return_value = {
        "id": "JIRA-101",
        "key": "JIRA-101",
        "url": "http://jira-mock:8080/browse/JIRA-101"
    }

    # Execute
    result = await orchestrator.process_incident(initial_state)

    # Assertions
    assert result["status"] == "completed"
    assert len(result["relevant_files"]) == 3
    assert result["relevant_files"][0]["file_path"] == "src/plugins/search-elasticsearch/client.js"
    assert result["relevant_files"][0]["relevance_score"] == 0.96


@pytest.mark.asyncio
async def test_e2e_incident_failure_handling(orchestrator, mock_llm, mock_services):
    """
    Test: Graceful handling of service failures
    """
    initial_state = {
        "id": "test_incident_004",
        "title": "Test Incident",
        "description": "Test incident description",
        "status": "pending"
    }

    # Mock LLM success
    mock_llm.parse_incident.return_value = ParsedIncident(
        title="Test",
        description="Test"
    )

    # Mock Jira failure
    mock_services["jira"].create_issue.side_effect = Exception("Jira connection failed")

    # Execute
    result = await orchestrator.process_incident(initial_state)

    # Assertions - should handle gracefully
    assert result["status"] in ["completed", "failed"]
    # May still complete but without ticket
    if result["status"] == "failed":
        assert "error" in result or result.get("ticket_id") is None
