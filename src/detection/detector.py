"""
Harassment detection engine.

Supports English, Tamil, and Tanglish comments using:
1. Keyword / pattern matching  — fast, fully offline
2. AI provider (configurable)  — higher accuracy for nuanced / mixed-language text

Supported AI providers (set AI_PROVIDER in .env):
  openai  — OpenAI GPT-4o          (default, requires OPENAI_API_KEY)
  gemini  — Google Gemini 2.0 Flash (best Tamil/Tanglish, requires GEMINI_API_KEY)
  ollama  — Local Llama via Ollama  (free, self-hosted, requires Ollama running locally)

Language detection uses Tamil Unicode heuristic → Tanglish keyword heuristic → langdetect.

Keywords are stored in the harassment_keywords DB table (seeded automatically on first run).
Add new keywords via:  python scripts/manage.py add-keyword
"""
import os
import re
import json
from loguru import logger

# ── AI provider config (from .env) ────────────────────────────
AI_PROVIDER    = os.getenv("AI_PROVIDER", "openai").lower()   # openai | gemini | ollama
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL", "llama3.3")

# ── Shared moderation prompt ───────────────────────────────────
_SYSTEM_PROMPT = (
    "You are a Tamil/English social-media content moderator. "
    "Comments may be in any of these forms:\n"
    "  • English\n"
    "  • Tamil (Unicode script: தமிழ்)\n"
    "  • Tanglish (Tamil words written in English letters, "
    "e.g. 'naye', 'thevdiya', 'loosu', 'punda')\n"
    "  • A mix of the above\n\n"
    "Decide whether the comment is harassing, abusive, threatening, or highly offensive. "
    "Consider cultural context — many Tanglish words are severe insults even if "
    "they look harmless in English.\n\n"
    "Reply ONLY with valid JSON, no markdown:\n"
    '{"harassing": true/false, "score": 0-100, "reason": "brief explanation"}'
)


# ── DB-backed keyword loader ────────────────────────────────────
#
# Keywords are stored in harassment_tracker.harassment_keywords.
# The first call loads them from the DB and caches them in-process.
# Call reload_keywords() to refresh the cache after adding new ones.
#
# language column values: tanglish | tamil | english | universal
#   universal → matched regardless of detected language

_kw_cache: dict[str, list[str]] | None = None  # keyed by language value


def _load_keywords() -> dict[str, list[str]]:
    """Load active keywords from the DB grouped by language."""
    try:
        from src.db.database import SessionLocal
        from src.db.models import HarassmentKeyword
        db = SessionLocal()
        try:
            rows = db.query(HarassmentKeyword).filter_by(is_active=True).all()
            grouped: dict[str, list[str]] = {}
            for row in rows:
                grouped.setdefault(row.language, []).append(row.keyword)
            logger.debug(
                f"Loaded {sum(len(v) for v in grouped.values())} keywords from DB "
                f"({len(grouped)} language buckets)"
            )
            return grouped
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Could not load keywords from DB (using empty set): {e}")
        return {}


def _keywords() -> dict[str, list[str]]:
    """Return cached keyword map, loading from DB on first call."""
    global _kw_cache
    if _kw_cache is None:
        _kw_cache = _load_keywords()
    return _kw_cache


def reload_keywords() -> int:
    """
    Force-reload keyword cache from the DB.
    Call this after adding new keywords so the running process picks them up.
    Returns total number of active keywords loaded.
    """
    global _kw_cache
    _kw_cache = _load_keywords()
    return sum(len(v) for v in _kw_cache.values())



# ── Language detection ─────────────────────────────────────────

def detect_language(text: str) -> str:
    """
    Detect comment language: tamil | tanglish | english | other | unknown.

    Order of checks:
      1. Tamil Unicode characters → "tamil"
      2. Known Tanglish keywords in Latin script → "tanglish"
      3. langdetect fallback → "english" / "other"
    """
    if re.search(r"[\u0B80-\u0BFF]", text):
        return "tamil"

    lower = text.lower()
    for kw in _keywords().get("tanglish", []):
        if kw in lower:
            return "tanglish"

    try:
        from langdetect import detect
        lang = detect(text)
        return "english" if lang == "en" else "other"
    except Exception:
        return "unknown"


# ── Keyword-based detection ────────────────────────────────────

def keyword_detect(text: str, language: str) -> tuple[bool, int, list[str]]:
    """
    Keyword/pattern match against all relevant lists loaded from the DB.
    Returns (is_harassing, score 0-100, matched_keywords).
    Score: 25 per match, capped at 100.
    """
    lower = text.lower()
    matched: list[str] = []
    kws = _keywords()

    # universal keywords always apply
    matched += [kw for kw in kws.get("universal", []) if kw in lower]

    if language in ("english", "unknown", "other"):
        matched += [kw for kw in kws.get("english", []) if kw in lower]

    if language in ("tanglish", "unknown", "other"):
        matched += [kw for kw in kws.get("tanglish", []) if kw in lower]

    if language == "tamil":
        matched += [kw for kw in kws.get("tamil", []) if kw in text]

    score = min(100, len(matched) * 25)
    return (len(matched) > 0, score, matched)


# ── AI provider implementations ────────────────────────────────

def _parse_ai_response(raw: str) -> tuple[bool, int, str]:
    """Parse the JSON response common to all AI providers."""
    try:
        data = json.loads(raw)
        return (
            bool(data.get("harassing", False)),
            int(data.get("score", 0)),
            str(data.get("reason", "")),
        )
    except Exception:
        logger.warning(f"Could not parse AI response JSON: {raw[:200]}")
        return False, 0, f"parse error: {raw[:100]}"


def _ai_openai(text: str) -> tuple[bool, int, str]:
    """GPT-4o via OpenAI API."""
    if not OPENAI_API_KEY:
        return False, 0, "OpenAI not configured (OPENAI_API_KEY missing)"
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Comment: {text}"},
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0,
        )
        return _parse_ai_response(response.choices[0].message.content)
    except Exception as e:
        logger.warning(f"[OpenAI] Detection failed: {e}")
        return False, 0, f"OpenAI error: {e}"


def _ai_gemini(text: str) -> tuple[bool, int, str]:
    """
    Gemini 2.0 Flash via Google Generative AI SDK.
    Best overall for Tamil and Tanglish content.
    Install: pip install google-generativeai
    """
    if not GEMINI_API_KEY:
        return False, 0, "Gemini not configured (GEMINI_API_KEY missing)"
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=_SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=200,
                temperature=0,
            ),
        )
        response = model.generate_content(f"Comment: {text}")
        return _parse_ai_response(response.text)
    except Exception as e:
        logger.warning(f"[Gemini] Detection failed: {e}")
        return False, 0, f"Gemini error: {e}"


def _ai_ollama(text: str) -> tuple[bool, int, str]:
    """
    Local Llama model via Ollama (free, self-hosted).
    Install Ollama: https://ollama.com
    Pull model: ollama pull llama3.3
    Set OLLAMA_MODEL and OLLAMA_BASE_URL in .env.
    """
    try:
        import requests as _req
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Comment: {text}"},
            ],
            "stream": False,
            "format": "json",
        }
        resp = _req.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return _parse_ai_response(content)
    except Exception as e:
        logger.warning(f"[Ollama] Detection failed: {e}")
        return False, 0, f"Ollama error: {e}"


# Provider dispatch table
_AI_PROVIDERS = {
    "openai": _ai_openai,
    "gemini": _ai_gemini,
    "ollama": _ai_ollama,
}


def ai_detect(text: str) -> tuple[bool, int, str]:
    """
    Run harassment detection using the configured AI provider.
    Provider is selected by AI_PROVIDER env var (openai | gemini | ollama).
    Returns (is_harassing, score 0-100, reasoning).
    """
    provider_fn = _AI_PROVIDERS.get(AI_PROVIDER)
    if not provider_fn:
        logger.error(f"Unknown AI_PROVIDER='{AI_PROVIDER}'. Use: openai, gemini, ollama")
        return False, 0, f"Unknown provider: {AI_PROVIDER}"

    logger.debug(f"Running AI detection with provider={AI_PROVIDER}")
    return provider_fn(text)


# ── Main analysis pipeline ─────────────────────────────────────

def _ai_is_available() -> bool:
    """Check whether any AI provider is actually configured."""
    if AI_PROVIDER == "openai" and OPENAI_API_KEY:
        return True
    if AI_PROVIDER == "gemini" and GEMINI_API_KEY:
        return True
    if AI_PROVIDER == "ollama":
        return True   # Ollama doesn't need an API key
    return False


def analyse_comment(text: str) -> dict:
    """
    Full analysis pipeline for a single comment.

    Steps:
      1. Detect language (tamil / tanglish / english / other)
      2. Keyword match
      3. AI analysis (if provider configured)
      4. Combine scores — keyword result locks in a positive; AI score adds confidence

    Returns a dict compatible with the Comment ORM model.
    """
    if not text or not text.strip():
        return {
            "is_harassing": False,
            "harassment_score": 0,
            "detected_language": "unknown",
            "detection_reasons": {"keywords_matched": [], "keyword_score": 0,
                                   "ai_provider": None, "ai_score": 0, "ai_reason": ""},
        }

    language = detect_language(text)
    kw_harassing, kw_score, kw_matches = keyword_detect(text, language)

    ai_harassing = False
    ai_score = 0
    ai_reason = ""

    # Call AI when:
    #  - a keyword hit was found (confirm / get reasoning), OR
    #  - text is non-trivial (> 10 chars) so AI can catch what keywords miss
    if _ai_is_available() and (kw_harassing or len(text.strip()) > 10):
        ai_harassing, ai_score, ai_reason = ai_detect(text)

    # Final decision — either signal is enough to flag
    final_score = max(kw_score, ai_score)
    is_harassing = kw_harassing or ai_harassing

    return {
        "is_harassing": is_harassing,
        "harassment_score": final_score,
        "detected_language": language,
        "detection_reasons": {
            "keywords_matched": kw_matches,
            "keyword_score": kw_score,
            "ai_provider": AI_PROVIDER if _ai_is_available() else None,
            "ai_score": ai_score,
            "ai_reason": ai_reason,
        },
    }
