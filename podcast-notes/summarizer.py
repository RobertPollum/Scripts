"""
Send a podcast transcript to an LLM and get back a filled Obsidian note.

Supports any OpenAI-compatible API (OpenAI, Azure, local vLLM, Ollama, etc.)
by configuring OPENAI_BASE_URL in .env.
"""

from __future__ import annotations

from openai import OpenAI

import config
from scraper import EpisodeMeta

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert note-taker building long-term knowledge in Obsidian.

Using the following Modern Wisdom podcast transcript, generate a clean,
human-readable Obsidian markdown note intended for personal reference
and future linking.

REQUIREMENTS:
- Treat this as a topical conversation, not a motivational summary
- Be neutral, accurate, and concept-focused
- Assume the reader may revisit this years later
- Use only:
  - Internal Obsidian links [[Like This]]
  - Public, durable external links (Wikipedia, official sites)
- Do NOT reference ChatGPT, prompts, or private artifacts
- Do NOT invent facts not supported by the transcript

STRUCTURE THE NOTE AS:

# Modern Wisdom #[Episode Number] — [Guest Name]
**Episode Title**

**Guest:**
**Host:** Chris Williamson
**Episode #:**
**Transcript Source:** [PODCAST TRANSCRIPT URL — explicitly note Podscripts if applicable]

---

## 🧠 Top-Level Summary
Concise but information-dense overview of the conversation.

## 🚩 Core Concepts
Bullet list of major ideas (written to be linkable later).

## 🧠 Key Insights
Short sections explaining how and why the ideas matter.

## 🛠 Practical Strategies / Mental Models
Only if present in the transcript; no motivational filler.

## 🎯 Learning Objectives
What someone should understand better after reading this note.

## 🔗 Related Concepts (for linking)
List of concepts that should become atomic notes.

## 📚 External Resources
Only durable, public resources.

## 🏷 Tags
Concise, lowercase, reusable tags.
"""


def generate_notes(transcript: str, meta: EpisodeMeta) -> str:
    """
    Call the configured LLM with the transcript and return the filled
    Obsidian markdown note.
    """
    if not config.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. "
            "Copy .env.example to .env and fill in your key."
        )

    client = OpenAI(
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_BASE_URL,
    )

    user_message = (
        f"Episode Number: {meta.number}\n"
        f"Guest: {meta.guest}\n"
        f"Episode Title: {meta.title}\n"
        f"Transcript Source: {meta.url} (via Podscripts)\n\n"
        f"TRANSCRIPT:\n{transcript}"
    )

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
        max_tokens=8192,
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned an empty response.")

    return content.strip()
