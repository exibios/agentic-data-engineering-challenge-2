# pipeline/metadata_service.py
"""Service for retrieving ClinicalTrials.gov study metadata with resilient local fallback."""

import logging
from typing import Any, Dict
import httpx

logger = logging.getLogger("metadata_service")

CLINICAL_TRIALS_API_BASE = "https://clinicaltrials.gov/api/v2/studies"


def fetch_study_metadata_or_fallback(
    nct_id: str, filename: str, gcs_uri: str
) -> Dict[str, Any]:
  """Fetches study metadata from ClinicalTrials.gov API v2 with graceful local fallback.

  If external network access is unavailable, times out, or the API returns non-200,
  this function generates a structured metadata record using the file URI and NCTId.
  """
  last_two = nct_id[-2:] if len(nct_id) >= 2 else "00"
  cdn_url = f"https://cdn.clinicaltrials.gov/large-docs/{last_two}/{nct_id}/{filename}"

  metadata: Dict[str, Any] = {
      "nct_id": nct_id,
      "brief_title": f"Clinical Study {nct_id}",
      "overall_status": "UNKNOWN",
      "doc_filename": filename,
      "cdn_url": cdn_url,
      "gcs_uri": gcs_uri,
  }

  try:
    url = f"{CLINICAL_TRIALS_API_BASE}/{nct_id}"
    with httpx.Client(timeout=4.0, follow_redirects=True) as client:
      resp = client.get(url)
      if resp.status_code == 200:
        data = resp.json()
        protocol = data.get("protocolSection", {})
        metadata["brief_title"] = protocol.get(
            "identificationModule", {}
        ).get("briefTitle", metadata["brief_title"])
        metadata["overall_status"] = protocol.get("statusModule", {}).get(
            "overallStatus", metadata["overall_status"]
        )
        logger.info(f"✅ Retrieved ClinicalTrials.gov API metadata for {nct_id}")
  except Exception as e:
    logger.warning(
        f"Could not fetch ClinicalTrials.gov API metadata ({e}). Using resilient fallback metadata for {nct_id}."
    )

  return metadata

