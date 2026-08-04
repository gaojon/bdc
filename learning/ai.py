"""DeepSeek API integration: article and quiz generation."""

import json
import logging
import re

from openai import OpenAI

from utils.config import get_config

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Get or create the DeepSeek API client (lazy singleton)."""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=get_config("deepseek.api_key"),
            base_url=get_config("deepseek.base_url"),
            timeout=get_config("deepseek.timeout_seconds", 120),
        )
    return _client


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_article_prompt(
    interests: list[str],
    word_list: list[str],
    complexity: int,
    word_count: int = 500,
) -> tuple[str, str]:
    """Build system and user prompts for article generation.

    Returns (system_prompt, user_prompt).
    """
    system_prompt = (
        "You are an English article writer for language learners. "
        "Write engaging, natural articles that incorporate target vocabulary "
        "words seamlessly. Do NOT force every word in — quality over quantity."
    )

    interest_str = ", ".join(interests) if interests else "general topics"
    word_str = "\n".join(f"- {w}" for w in word_list)
    min_words = get_config("article.min_hit_words", 25)

    user_prompt = f"""Write an article in English with the following requirements:

- Topic/Interest: {interest_str}
- Target word count: ~{word_count} words
- Sentence complexity level: {complexity}/9 (1=very simple, 9=native-level complex)
- Target vocabulary words to include (try to use as many as possible, minimum {min_words}):

{word_str}

Return your response as a JSON object with this exact structure:
{{
  "title": "article title",
  "content": "full article text with paragraphs separated by \\n\\n",
  "hit_words": ["word1", "word2"],
  "glossary": {{
    "word1": "brief definition in the context of this article",
    "word2": "brief definition in the context of this article"
  }}
}}

Important:
- The article must flow naturally. Do NOT force every word in — quality over quantity.
- Each hit_word must be exactly as provided (preserve case, hyphenation, etc.).
- The glossary should contain a short, context-appropriate definition for each hit_word.
- Return ONLY the JSON object, no other text."""

    return system_prompt, user_prompt


def build_quiz_prompt(title: str, content: str) -> tuple[str, str]:
    """Build system and user prompts for quiz generation.

    Returns (system_prompt, user_prompt).
    """
    system_prompt = (
        "You are an English test creator. Create reading comprehension "
        "questions based on the provided article."
    )

    user_prompt = f"""Based on the following article, create exactly 5 multiple-choice quiz questions.

Article title: {title}

Article content:
{content}

Requirements:
- Each question must have 4 options (A/B/C/D), only ONE correct answer
- Questions must test reading comprehension, NOT vocabulary memorization
- Include evidence (quote/excerpt) from the article for each correct answer
- Distractors (wrong options) should be plausible but clearly wrong

Return your response as a JSON object with this exact structure:
{{
  "questions": [
    {{
      "id": 1,
      "question": "question text",
      "options": {{ "A": "...", "B": "...", "C": "...", "D": "..." }},
      "correct": "A",
      "explanation": "explanation with evidence from the article"
    }}
  ]
}}

Return ONLY the JSON object, no other text."""

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


def validate_article_response(data: dict) -> dict | None:
    """Validate article response has required fields. Returns data or None."""
    required = ["title", "content", "hit_words", "glossary"]
    for field in required:
        if field not in data:
            logger.warning("Article response missing field: %s", field)
            return None

    if not isinstance(data["hit_words"], list):
        logger.warning("hit_words is not a list")
        return None

    if not isinstance(data["glossary"], dict):
        logger.warning("glossary is not a dict")
        return None

    return data


def validate_quiz_response(data: dict) -> dict | None:
    """Validate quiz response has exactly 5 questions. Returns data or None."""
    if "questions" not in data:
        logger.warning("Quiz response missing 'questions'")
        return None

    questions = data["questions"]
    if not isinstance(questions, list) or len(questions) != 5:
        logger.warning("Quiz has %d questions (expected 5)", len(questions))
        return None

    for q in questions:
        required = ["id", "question", "options", "correct", "explanation"]
        for field in required:
            if field not in q:
                logger.warning("Quiz question %s missing field: %s", q.get("id"), field)
                return None
        if not isinstance(q["options"], dict) or len(q["options"]) != 4:
            logger.warning("Quiz question %s: options must be a dict with 4 entries", q.get("id"))
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
    """Call DeepSeek API to generate an article incorporating target words.

    Args:
        word_strings: List of word text strings to include.
        interests: List of interest topic names.
        complexity: Sentence complexity 1-9.
        word_count: Target article word count (from config if None).

    Returns:
        dict with keys: title, content, hit_words, glossary.
        None on any failure (D-16: no retry).
    """
    if word_count is None:
        word_count = get_config("article.target_word_count", 500)

    model = get_config("deepseek.model", "deepseek-chat")
    sys_prompt, user_prompt = build_article_prompt(
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
            max_tokens=4096,
        )
        content = response.choices[0].message.content
        data = parse_json_response(content)
        return validate_article_response(data) if data else None

    except Exception as e:
        logger.error("Article generation failed: %s", e)
        return None


def generate_quiz(title: str, content: str) -> dict | None:
    """Call DeepSeek API to generate quiz questions for an article.

    Args:
        title: Article title.
        content: Article content text.

    Returns:
        dict with key 'questions' (list of 5 question dicts).
        None on any failure (D-16: no retry).
    """
    model = get_config("deepseek.model", "deepseek-chat")
    sys_prompt, user_prompt = build_quiz_prompt(title, content)

    try:
        client = get_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2048,
        )
        content = response.choices[0].message.content
        data = parse_json_response(content)
        return validate_quiz_response(data) if data else None

    except Exception as e:
        logger.error("Quiz generation failed: %s", e)
        return None
