"""Code analysis agent — queries vector store and analyzes relevant code."""

import logging
import json
from typing import Optional
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.llm_client import LLMClient
from app.services.vector_store import VectorStore
from app.services.event_store import EventStore
from app.models.incident import IncidentState

logger = logging.getLogger(__name__)


class CodeChunk(BaseModel):
    """A code chunk from vector store."""
    file_path: str
    content: str
    similarity_score: Optional[float] = None


class CodeAnalysis(BaseModel):
    """Analysis result from code examination."""
    analysis_summary: str = Field(..., description="Summary of code analysis findings")
    relevant_files: list[str] = Field(default_factory=list, description="List of relevant file paths")
    functions_involved: list[str] = Field(default_factory=list, description="Function names that may be involved")
    potential_root_causes: list[str] = Field(default_factory=list, description="Potential root causes identified")
    degraded: bool = Field(False, description="True if analysis is degraded due to LLM failure")


async def code_analysis_agent(state: IncidentState) -> dict:
    """
    Analyze incident using code from vector store.

    1. Load ParsedIncident from state
    2. Build query from service + error_type + symptoms
    3. Query vector store (n_results=10)
    4. Expand context: top-3 files -> expand with 15 more results
    5. Deduplicate and keep top-20
    6. Verify file paths exist in index
    7. Build LLM prompt with verified chunks
    8. Parse CodeAnalysis
    9. On failure: return degraded analysis
    10. Return state update with code_analysis
    """
    settings = get_settings()
    vector_store = VectorStore()
    llm_client = LLMClient()
    event_store = EventStore()

    try:
        incident_id = state.get("incident_id", "")
        parsed = state.get("parsed_incident", {})

        if not parsed:
            logger.warning("No parsed_incident in state, skipping code analysis")
            return {
                "code_analysis": CodeAnalysis(
                    analysis_summary="Skipped: no parsed incident data",
                    degraded=True
                ).model_dump()
            }

        # Build query
        affected_service = parsed.get("affected_service", "")
        error_type = parsed.get("error_type", "")
        symptoms = parsed.get("symptoms", [])

        query = f"{affected_service} {error_type} {' '.join(symptoms)}"
        logger.info(f"Code analysis query: {query}")

        # Query vector store
        try:
            results = vector_store.query(query, n_results=10)
        except Exception as e:
            logger.error(f"Vector store query failed: {e}")
            return {
                "code_analysis": CodeAnalysis(
                    analysis_summary="Code analysis unavailable — vector store error.",
                    degraded=True
                ).model_dump()
            }

        if not results:
            logger.info("No results from vector store")
            return {
                "code_analysis": CodeAnalysis(
                    analysis_summary="No relevant code found in repository.",
                    degraded=False
                ).model_dump()
            }

        # Extract top file paths
        top_files = []
        for result in results[:3]:
            if "file_path" in result:
                top_files.append(result["file_path"])

        # Expand context from top files
        expanded_chunks = []
        if top_files:
            try:
                expanded = vector_store.expand_context(top_files, query, n_results=15)
                expanded_chunks = expanded if expanded else []
            except Exception as e:
                logger.warning(f"Context expansion failed: {e}")
                expanded_chunks = []

        # Combine and deduplicate by content
        all_chunks = results + expanded_chunks
        seen_content = set()
        deduplicated = []

        for chunk in all_chunks:
            content = chunk.get("content", "")
            if content and content not in seen_content:
                seen_content.add(content)
                deduplicated.append(chunk)
                if len(deduplicated) >= 20:
                    break

        # Verify file paths exist in index
        verified_chunks = []
        for chunk in deduplicated:
            file_path = chunk.get("file_path")
            if file_path:
                try:
                    if vector_store.file_exists(file_path):
                        verified_chunks.append(chunk)
                except Exception as e:
                    logger.warning(f"File existence check failed for {file_path}: {e}")
                    # Include anyway if check fails
                    verified_chunks.append(chunk)

        if not verified_chunks:
            logger.warning("No verified chunks found")
            return {
                "code_analysis": CodeAnalysis(
                    analysis_summary="Code analysis unavailable — no verified code found.",
                    degraded=True
                ).model_dump()
            }

        # Build prompt with chunks
        chunks_text = "\n\n---\n\n".join([
            f"File: {c.get('file_path', 'unknown')}\n{c.get('content', '')}"
            for c in verified_chunks
        ])

        file_list = [c.get("file_path") for c in verified_chunks if c.get("file_path")]

        system_prompt = """You are an SRE code analyst for Reaction Commerce (Node.js/GraphQL e-commerce).
Analyze incident reports by examining provided code chunks.
CRITICAL: only cite file_path values that appear in the provided chunk list — never invent paths."""

        user_prompt = f"""Analyze this incident in the context of the provided code:

Incident: {json.dumps(parsed, indent=2)}

Code chunks (these are the ONLY files you may cite):
{chunks_text}

Provide a JSON response matching:
{{
  "analysis_summary": "Summary of findings",
  "relevant_files": ["file1.js", "file2.js"],
  "functions_involved": ["functionName1", "functionName2"],
  "potential_root_causes": ["cause1", "cause2"]
}}

Return ONLY valid JSON."""

        # Call LLM twice on failure
        response = None
        for attempt in range(2):
            try:
                response = await llm_client.call(system_prompt, user_prompt)
                break
            except Exception as e:
                logger.warning(f"LLM call attempt {attempt + 1} failed: {e}")
                if attempt == 1:
                    # Both attempts failed
                    return {
                        "code_analysis": CodeAnalysis(
                            analysis_summary="Code analysis unavailable — proceeding with text-only triage.",
                            relevant_files=[],
                            degraded=True
                        ).model_dump()
                    }

        # Parse response
        try:
            analysis_json = json.loads(LLMClient.extract_json(response))
            analysis = CodeAnalysis(**analysis_json)

            # Validate that cited files exist in our list
            cited_files = analysis.relevant_files or []
            for cited in cited_files:
                if cited not in file_list:
                    logger.warning(f"LLM cited file not in verified list: {cited}")
                    # Remove from analysis to maintain integrity
                    analysis.relevant_files = [f for f in cited_files if f in file_list]

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse code analysis response: {e}")
            analysis = CodeAnalysis(
                analysis_summary="Code analysis unavailable — parsing failed.",
                relevant_files=file_list[:5],
                degraded=True
            )

        # Log to event store
        await event_store.log_event(
            incident_id=incident_id,
            event_type="code_analysis_completed",
            data={
                "analysis": analysis.model_dump(),
                "chunks_examined": len(verified_chunks)
            }
        )

        return {"code_analysis": analysis.model_dump()}

    except Exception as e:
        logger.exception(f"Code analysis agent failed: {e}")
        return {
            "code_analysis": CodeAnalysis(
                analysis_summary="Code analysis unavailable — proceeding with text-only triage.",
                degraded=True
            ).model_dump()
        }
