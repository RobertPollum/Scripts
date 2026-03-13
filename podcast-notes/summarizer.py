"""
Send a podcast transcript to an LLM and get back a filled Obsidian note.

Supports any OpenAI-compatible API (OpenAI, Azure, local vLLM, Ollama, etc.)
by configuring OPENAI_BASE_URL in .env.
"""

from __future__ import annotations

import calendar
import datetime
import time
from collections import deque
from threading import Lock

import requests

from openai import OpenAI

import config
from scraper import EpisodeMeta


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """
    Sliding-window rate limiter that enforces:
    - requests per minute (RPM)
    - tokens per minute (TPM)
    - optional hard cap on total tokens for the entire run
    """

    def __init__(
        self,
        rpm_limit: int = 0,
        tpm_limit: int = 0,
        run_token_cap: int = 0,
    ) -> None:
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit
        self.run_token_cap = run_token_cap

        self._lock = Lock()
        self._request_times: deque[float] = deque()
        self._token_events: deque[tuple[float, int]] = deque()
        self.total_tokens_used: int = 0

    def _purge_old(self, now: float) -> None:
        cutoff = now - 60.0
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()
        while self._token_events and self._token_events[0][0] < cutoff:
            self._token_events.popleft()

    def check_token_cap(self, estimated_tokens: int) -> None:
        """Raise RuntimeError if adding estimated_tokens would exceed the run cap."""
        if self.run_token_cap > 0:
            with self._lock:
                if self.total_tokens_used + estimated_tokens > self.run_token_cap:
                    raise RuntimeError(
                        f"Run token cap reached: {self.total_tokens_used:,} used, "
                        f"cap is {self.run_token_cap:,}. "
                        "Increase OPENAI_RUN_TOKEN_CAP or re-run to continue."
                    )

    def wait_if_needed(self, estimated_tokens: int = 0) -> None:
        """Block until RPM and TPM windows allow the next request."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._purge_old(now)

                rpm_ok = (self.rpm_limit == 0) or (len(self._request_times) < self.rpm_limit)
                current_tpm = sum(t for _, t in self._token_events)
                tpm_ok = (self.tpm_limit == 0) or (current_tpm + estimated_tokens <= self.tpm_limit)

                if rpm_ok and tpm_ok:
                    break

            oldest_req = self._request_times[0] if self._request_times else None
            oldest_tok = self._token_events[0][0] if self._token_events else None

            candidates = [t for t in [oldest_req, oldest_tok] if t is not None]
            if candidates:
                sleep_until = min(candidates) + 60.0
                sleep_for = max(0.0, sleep_until - time.monotonic())
                if sleep_for > 0:
                    print(f"    ⏳ Rate limit — waiting {sleep_for:.1f}s …", flush=True)
                    time.sleep(sleep_for)
            else:
                time.sleep(1.0)

    def record(self, tokens_used: int) -> None:
        """Record that a request just completed using tokens_used tokens."""
        with self._lock:
            now = time.monotonic()
            self._request_times.append(now)
            self._token_events.append((now, tokens_used))
            self.total_tokens_used += tokens_used


_default_limiter: RateLimiter | None = None


def get_default_limiter() -> RateLimiter:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = RateLimiter(
            rpm_limit=config.OPENAI_RPM_LIMIT,
            tpm_limit=config.OPENAI_TPM_LIMIT,
            run_token_cap=config.OPENAI_RUN_TOKEN_CAP,
        )
    return _default_limiter


def reset_default_limiter() -> None:
    """Reset the module-level limiter (useful between batch runs)."""
    global _default_limiter
    _default_limiter = None


# ---------------------------------------------------------------------------
# Monthly budget enforcement via the OpenAI Costs API
# ---------------------------------------------------------------------------

def fetch_month_spend_usd() -> float:
    """
    Query the OpenAI Costs API and return the total USD spend for the current
    calendar month.  Requires OPENAI_ADMIN_KEY to be set.

    Returns 0.0 and prints a warning if the admin key is missing or the request
    fails, so a transient error never silently blocks all requests.
    """
    if not config.OPENAI_ADMIN_KEY:
        print(
            "    ⚠️  OPENAI_ADMIN_KEY not set — budget check skipped.",
            flush=True,
        )
        return 0.0

    now = datetime.datetime.now(datetime.timezone.utc)
    # First second of the current month
    month_start = datetime.datetime(now.year, now.month, 1, tzinfo=datetime.timezone.utc)
    # First second of the next month (exclusive end)
    last_day = calendar.monthrange(now.year, now.month)[1]
    month_end = datetime.datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=datetime.timezone.utc)

    url = "https://api.openai.com/v1/organization/costs"
    headers = {
        "Authorization": f"Bearer {config.OPENAI_ADMIN_KEY}",
        "Content-Type": "application/json",
    }
    params = {
        "start_time": int(month_start.timestamp()),
        "end_time": int(month_end.timestamp()),
        "bucket_width": "1d",
        "limit": 31,
    }

    total_usd = 0.0
    page_cursor = None
    while True:
        if page_cursor:
            params["page"] = page_cursor
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            print(f"    ⚠️  Costs API error ({exc}) — budget check skipped.", flush=True)
            return 0.0

        data = resp.json()
        for bucket in data.get("data", []):
            for result in bucket.get("results", []):
                total_usd += result.get("amount", {}).get("value", 0.0)

        page_cursor = data.get("next_page")
        if not page_cursor:
            break

    return total_usd


def check_monthly_budget() -> None:
    """
    Fetch the current month's spend and raise BudgetExceededError if it is at
    or above OPENAI_MONTHLY_BUDGET_USD.  No-ops when budget is 0 (disabled) or
    admin key is missing.
    """
    if config.OPENAI_MONTHLY_BUDGET_USD <= 0:
        return
    spent = fetch_month_spend_usd()
    if spent >= config.OPENAI_MONTHLY_BUDGET_USD:
        raise RuntimeError(
            f"Monthly budget exceeded: ${spent:.4f} spent of "
            f"${config.OPENAI_MONTHLY_BUDGET_USD:.2f} limit. "
            "Increase OPENAI_MONTHLY_BUDGET_USD or wait until next month."
        )

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
        max_completion_tokens=8192,
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned an empty response.")

    return content.strip()


def generate_notes_with_limit(
    transcript: str,
    meta: EpisodeMeta,
    *,
    limiter: RateLimiter | None = None,
    request_delay: float | None = None,
) -> str:
    """
    Rate-limit-aware version of generate_notes.

    Uses the module-level default RateLimiter (configured from config.*) unless
    a custom limiter is passed.  Also enforces a minimum per-request delay.
    """
    if limiter is None:
        limiter = get_default_limiter()

    if request_delay is None:
        request_delay = config.OPENAI_REQUEST_DELAY

    # Rough token estimate: system prompt + user message chars / 4, plus max output
    estimated_input = (len(SYSTEM_PROMPT) + len(transcript) + 256) // 4
    estimated_total = estimated_input + 8192

    # Monthly dollar budget check (fetches live spend from Costs API)
    check_monthly_budget()

    # Hard cap check before we even start waiting
    limiter.check_token_cap(estimated_total)

    # Wait for RPM / TPM window
    limiter.wait_if_needed(estimated_total)

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

    max_retries = 6
    backoff = 5.0
    response = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_completion_tokens=8192,
            )
            break
        except Exception as exc:
            err_str = str(exc)
            is_rate_limit = "429" in err_str or "rate_limit_exceeded" in err_str or "Rate limit" in err_str
            if is_rate_limit and attempt < max_retries - 1:
                wait = backoff * (2 ** attempt)
                print(f"\n    ⏳ 429 rate limit — retrying in {wait:.0f}s (attempt {attempt + 1}/{max_retries}) …", flush=True)
                time.sleep(wait)
                continue
            raise

    actual_tokens = response.usage.total_tokens if response.usage else estimated_total
    limiter.record(actual_tokens)

    if request_delay > 0:
        time.sleep(request_delay)

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned an empty response.")

    return content.strip()


def generate_notes_from_template(
    *,
    transcript: str,
    meta: EpisodeMeta,
    template_markdown: str,
    created_date: str,
) -> str:
    if not config.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. "
            "Copy .env.example to .env and fill in your key."
        )

    client = OpenAI(
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_BASE_URL,
    )

    episode_title = meta.title
    if meta.guest and episode_title.startswith(meta.guest + " - "):
        episode_title = episode_title[len(meta.guest) + 3 :]

    template_prefilled = (
        template_markdown.replace("{{guest}}", meta.guest)
        .replace("{{date}}", created_date)
        .strip()
    )

    user_message = (
        "Fill in the following Obsidian note template using the transcript and metadata.\n\n"
        "RULES:\n"
        "- Return ONLY the final Obsidian markdown note (no code fences, no extra commentary).\n"
        "- Keep the structure and headings from the template.\n"
        "- Replace [Episode Number], [Guest Name], and **Episode Title** with the real values.\n"
        "- Use Transcript Source as: "
        f"{meta.url} (Podscripts)\n"
        "- In the TRANSCRIPT section, keep the placeholder (do not paste the transcript).\n\n"
        "METADATA:\n"
        f"Episode Number: {meta.number}\n"
        f"Guest: {meta.guest}\n"
        f"Episode Title: {episode_title}\n"
        f"Transcript Source URL: {meta.url}\n\n"
        "TEMPLATE:\n"
        f"{template_prefilled}\n\n"
        "TRANSCRIPT:\n"
        f"{transcript}"
    )

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
        max_completion_tokens=8192,
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned an empty response.")

    return content.strip()
