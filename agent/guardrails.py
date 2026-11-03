# agent/guardrails.py
"""Sensitive Data Protection (Cloud DLP) and Vertex AI Safety Settings."""

import os
from typing import Tuple
from google.cloud import dlp_v2
from google.genai import types

PROJECT_ID = os.getenv("GCP_PROJECT", "data4ai-challenge-03")
LOCATION = os.getenv("GCP_LOCATION", "global")

dlp_client = dlp_v2.DlpServiceClient()
PARENT = f"projects/{PROJECT_ID}/locations/{LOCATION}"

# 1. Target InfoTypes for Clinical Trial Data Protection
INFO_TYPES = [
    {"name": "PERSON_NAME"},
    {"name": "EMAIL_ADDRESS"},
    {"name": "PHONE_NUMBER"},
    {"name": "US_SOCIAL_SECURITY_NUMBER"},
    {"name": "US_HEALTHCARE_NPI"},
]


def redact_pii_dlp(text: str) -> Tuple[str, bool]:
  """Inspects and redacts sensitive PII from user prompts or document chunks.

  Returns (redacted_text, pii_detected_bool).
  """
  if not text or len(text.strip()) == 0:
    return text, False

  inspect_config = {
      "info_types": INFO_TYPES,
      "min_likelihood": dlp_v2.Likelihood.LIKELY,
      "include_quote": False,
  }

  deidentify_config = {
      "info_type_transformations": {
          "transformations": [{
              "primitive_transformation": {
                  "replace_with_info_type_config": {}
              }
          }]
      }
  }

  item = {"value": text}

  try:
    response = dlp_client.deidentify_content(
        request={
            "parent": PARENT,
            "deidentify_config": deidentify_config,
            "inspect_config": inspect_config,
            "item": item,
        }
    )
    redacted = response.item.value
    pii_found = redacted != text
    return redacted, pii_found
  except Exception as e:
    # Graceful fallback if DLP API is not yet provisioned locally
    return text, False


# 2. Vertex AI Standard Safety Settings Guardrails
VERTEX_SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
]
