"""
utils/gemini_client.py
──────────────────────
Thin wrapper around the Google Gemini SDK (google-genai >= 1.0).

Responsibilities (and only these):
  - Load GEMINI_API_KEY from the .env file.
  - Initialise a genai.Client pointed at gemini-2.5-flash.
  - Accept a rendered prompt string and return Gemini's raw text response.
  - Request JSON output via response_mime_type so the model reliably returns
    parseable JSON without markdown fences or surrounding prose.
  - Re-raise any SDK or network error as GeminiAPIError so callers never
    need to import google.genai themselves.

Nothing in this module constructs prompts, validates responses, retries
failures, or contains any business logic. That all lives in ai_engine.py.
"""

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class GeminiAPIError(Exception):
    """Raised when the Gemini API call fails for any reason.

    Wraps all google.genai SDK exceptions so callers have a single exception
    type to catch and never need to import the SDK directly.
    """


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MODEL_NAME = "gemini-flash-latest"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Load and return GEMINI_API_KEY from the environment.

    Loads .env first so the key is available even when the module is
    imported outside of a running Streamlit process (e.g. in test scripts).

    Raises:
        GeminiAPIError: if the key is missing or empty.
    """
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiAPIError(
            "GEMINI_API_KEY is not set. "
            "Add it to your .env file: GEMINI_API_KEY=your_key_here"
        )
    return key


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def call_gemini(prompt: str) -> str:
    """Send a prompt to Gemini and return the raw text response.

    Requests JSON output via response_mime_type so Gemini consistently
    returns parseable JSON without markdown fences or surrounding prose.

    Args:
        prompt: The fully rendered prompt string to send to the model.

    Returns:
        The raw text content of Gemini's response.

    Raises:
        GeminiAPIError: if the API key is missing, the network call fails,
            the SDK raises any exception, or the response contains no text.
    """
    try:
        api_key = _get_api_key()
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_MODEL_NAME,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        raw_text = response.text
    except GeminiAPIError:
        # Re-raise key errors unchanged — they already have a clear message.
        raise
    except Exception as exc:
        raise GeminiAPIError(
            f"Gemini API call failed ({type(exc).__name__}): {exc}"
        ) from exc

    if not raw_text or not raw_text.strip():
        raise GeminiAPIError(
            "Gemini returned an empty response. "
            "The model may have refused the prompt or hit a safety filter."
        )

    return raw_text
