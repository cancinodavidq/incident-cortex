"""
Seed script: loads 2 test incidents and runs them through the pipeline.
Used to pre-compute results for demo Plan B (pre-recorded responses).
"""
import asyncio
import httpx
import json
import time
from pathlib import Path
from datetime import datetime

API_URL = os.getenv("API_URL", "http://localhost:8000")

SEED_INCIDENTS = [
    {
        "title": "Checkout 500 Error - Stripe Payment Processing Failing",
        "description": """Critical production issue: All checkout attempts are failing with 500 Internal Server Error.
Error appears during payment processing step. Stripe webhook logs show uncaught exception.
Error in logs: TypeError: Cannot read property 'id' of undefined at processPayment
Stack trace points to payments-stripe plugin. Started ~30 minutes ago, affecting 100% of checkout attempts.
Revenue impact: ~$50k/hour.""",
        "reporter_email": "reporter@ecommerce.com"
    },
    {
        "title": "Product Search Returning Empty Results",
        "description": """Product search is broken. All search queries return 0 results regardless of search term.
The search bar is functional (accepts input), but results are always empty.
Started after last deployment 2 hours ago. Elasticsearch logs show query errors.
Error: "No active connection to Elasticsearch cluster"
Affects all users on the storefront. Customer complaints coming in rapidly.""",
        "reporter_email": "reporter2@ecommerce.com"
    }
]

async def seed_incidents():
    """POST each incident and poll for completion, save results"""
    seed_dir = Path("scripts/seed_data")
    seed_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, incident in enumerate(SEED_INCIDENTS):
            logger.info(f"Submitting incident {i+1}/{len(SEED_INCIDENTS)}: {incident['title']}")

            try:
                # Create incident
                resp = await client.post(
                    f"{API_URL}/api/incidents",
                    json={
                        "title": incident["title"],
                        "description": incident["description"],
                        "reporter_email": incident["reporter_email"]
                    }
                )
                resp.raise_for_status()
                incident_data = resp.json()
                incident_id = incident_data.get("id")

                logger.info(f"Created incident {incident_id}, waiting for analysis...")

                # Poll for completion (max 120 seconds)
                for poll_attempt in range(120):
                    await asyncio.sleep(1)

                    resp = await client.get(f"{API_URL}/api/incidents/{incident_id}")
                    resp.raise_for_status()
                    state = resp.json()

                    status = state.get("status", "unknown")
                    logger.info(f"  Incident status: {status}")

                    if status in ["completed", "failed"]:
                        # Save results
                        results_file = seed_dir / f"incident_{i+1}_results.json"
                        results_file.write_text(json.dumps(state, indent=2))
                        logger.info(f"Saved results to {results_file}")
                        break

                if status not in ["completed", "failed"]:
                    logger.warning(f"Incident {incident_id} did not complete within timeout")

            except Exception as e:
                logger.error(f"Error processing incident {i+1}: {e}")

    logger.info("Seeding complete!")

if __name__ == "__main__":
    import os
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    asyncio.run(seed_incidents())
