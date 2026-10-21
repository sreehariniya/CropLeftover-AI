"""Optional Gemini explanation. The app works fully without it.

The model only rephrases the rule-based results in the farmer's language.
It is told not to add facts, and the UI labels its output as AI-written.
"""
import os

LANG_NAMES = {"en": "English", "ta": "Tamil", "te": "Telugu", "hi": "Hindi"}
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def get_api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    try:  # Streamlit secrets (Community Cloud)
        import streamlit as st
        return st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None


def is_configured() -> bool:
    return bool(get_api_key())


def explain(summary: str, lang: str) -> str:
    """summary is plain text built from the rule results. Raises on API errors."""
    from google import genai

    client = genai.Client(api_key=get_api_key())
    prompt = (
        f"You help small farmers in India. Explain the following farm-residue suggestions "
        f"in simple {LANG_NAMES.get(lang, 'English')}, in at most 120 words, using short sentences. "
        f"Use ONLY the information given below. Do not add new uses, numbers, prices or safety "
        f"claims. Keep every caution. End by telling the farmer to confirm with a local "
        f"agricultural officer.\n\n{summary}"
    )
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    return (resp.text or "").strip()
