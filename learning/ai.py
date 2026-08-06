"""DeepSeek API integration: article and quiz generation."""

import json
import logging
import re

from openai import OpenAI

from utils.config import get_config

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Get or create the DeepSeek API client (lazy singleton).

    Raises ValueError if the API key is not configured, so callers can
    catch it and give the user a clear message.
    """
    global _client
    if _client is None:
        api_key = get_config("deepseek.api_key")
        if not api_key or api_key == "sk-your-api-key-here":
            raise ValueError(
                "DeepSeek API key is not configured. "
                "Set it in config/app_config.json or via the admin dashboard."
            )
        _client = OpenAI(
            api_key=api_key,
            base_url=get_config("deepseek.base_url"),
            timeout=get_config("deepseek.timeout_seconds", 120),
        )
    return _client


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_combined_prompt(
    interests: list[str],
    word_list: list[str],
    complexity: int,
    word_count: int = 500,
) -> tuple[str, str]:
    """Build system and user prompts for article + quiz generation in one call.

    Returns (system_prompt, user_prompt).
    """
    system_prompt = (
        "You are an English teacher. Write an engaging article for language "
        "learners that incorporates target vocabulary, then create 5 reading "
        "comprehension quiz questions about it. Return everything in one JSON."
    )

    interest_str = ", ".join(interests) if interests else "general topics"
    word_str = "\n".join(f"- {w}" for w in word_list)
    min_words = get_config("article.min_hit_words", 25)

    user_prompt = f"""Write an English article and create a quiz for it.

ARTICLE REQUIREMENTS:
- Topic/Interest: {interest_str}
- Target word count: ~{word_count} words
- Sentence complexity: {complexity}/9 (1=very simple, 9=native-level)
- Target vocabulary words (you MUST use at least {min_words} of these — aim for 80%+):
{word_str}

QUIZ REQUIREMENTS:
- Exactly 5 multiple-choice questions (A/B/C/D), one correct answer each
- Test reading comprehension, NOT vocabulary memorization
- Include evidence/quotes from the article in explanations
- Distractors should be plausible but clearly wrong

Return as JSON:
{{
  "title": "article title",
  "content": "full article text with paragraphs separated by \\n\\n",
  "hit_words": ["word1", "word2"],
  "glossary": {{"word1": "brief definition in context", "word2": "..."}},
  "quiz": {{
    "questions": [
      {{"id": 1, "question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correct": "A", "explanation": "..."}}
    ]
  }}
}}

Important:
- Article must flow naturally. Quality over quantity for hit_words.
- Each hit_word must be exactly as provided (preserve case/hyphens).
- Return ONLY the JSON object, no other text."""

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def parse_json_response(content: str | None) -> dict | None:
    """Parse AI response which may be wrapped in markdown code blocks.

    Tries: raw JSON → strip ```json fences → strip ``` fences.
    Returns parsed dict, or None on failure.
    """
    if content is None:
        return None

    content = content.strip()

    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try stripping ```json ... ``` fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse AI response as JSON: %s", content[:200])
    return None


def validate_response(data: dict) -> dict | None:
    """Validate combined article+quiz response has required fields."""
    required = ["title", "content", "hit_words", "glossary", "quiz"]
    for field in required:
        if field not in data:
            logger.warning("Response missing field: %s", field)
            return None

    if not isinstance(data["hit_words"], list):
        logger.warning("hit_words is not a list")
        return None

    if not isinstance(data["glossary"], dict):
        logger.warning("glossary is not a dict")
        return None

    quiz = data["quiz"]
    if "questions" not in quiz:
        logger.warning("Quiz missing 'questions'")
        return None

    questions = quiz["questions"]
    if not isinstance(questions, list) or len(questions) != 5:
        logger.warning("Quiz has %d questions (expected 5)", len(questions))
        return None

    for q in questions:
        for field in ["id", "question", "options", "correct", "explanation"]:
            if field not in q:
                logger.warning("Quiz question %s missing field: %s", q.get("id"), field)
                return None
        if not isinstance(q["options"], dict) or len(q["options"]) != 4:
            logger.warning("Quiz question %s: options must have 4 entries", q.get("id"))
            return None

    return data


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


def generate_article(
    word_strings: list[str],
    interests: list[str],
    complexity: int,
    word_count: int | None = None,
) -> dict | None:
    """Call DeepSeek API to generate article + quiz in a single call.

    Args:
        word_strings: List of word text strings to include.
        interests: List of interest topic names.
        complexity: Sentence complexity 1-9.
        word_count: Target article word count (from config if None).

    Returns:
        dict with keys: title, content, hit_words, glossary, quiz.
        None on any failure.
    """
    if word_count is None:
        word_count = get_config("article.target_word_count", 500)

    model = get_config("deepseek.model", "deepseek-v4-flash")
    sys_prompt, user_prompt = build_combined_prompt(
        interests, word_strings, complexity, word_count
    )

    try:
        client = get_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=6144,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = response.choices[0].message.content
        data = parse_json_response(content)
        return validate_response(data) if data else None

    except Exception as e:
        logger.error("Article generation failed: %s", e)
        return None
