"""
Scrape podscripts.co for Modern Wisdom episode listings and transcripts.

Episode list pages are mostly static HTML (requests + BeautifulSoup).
Transcript pages are JS-rendered, so we use Playwright.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, TimeoutError as PwTimeout

import config

# Default delay between transcript page loads (seconds)
DEFAULT_SCRAPE_DELAY = 8

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EpisodeMeta:
    number: int
    title: str            # full title including guest
    guest: str
    slug: str             # URL slug on podscripts
    url: str              # full podscripts URL
    description: str = ""

# ---------------------------------------------------------------------------
# Episode listing
# ---------------------------------------------------------------------------

_EPISODE_LINK_RE = re.compile(
    r"/podcasts/modern-wisdom/(\d+)-(.+)$"
)

_TITLE_RE = re.compile(
    r"^#(\d+)\s*-\s*(.+?)\s*-\s*(.+)$"
)


def _parse_title(raw: str) -> tuple[int, str, str]:
    """Return (episode_number, guest, episode_title) from a raw link title."""
    m = _TITLE_RE.match(raw.strip())
    if m:
        return int(m.group(1)), m.group(2).strip(), m.group(3).strip()
    # Fallback: try to at least get the number
    num_match = re.match(r"#(\d+)", raw.strip())
    num = int(num_match.group(1)) if num_match else 0
    return num, "", raw.strip()


def get_episode_list(
    max_pages: int = 200,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[EpisodeMeta]:
    """
    Scrape the Modern Wisdom listing pages and return episode metadata.

    Args:
        max_pages: Upper bound on listing pages to fetch.
        progress_cb: Optional callback(page_num, episodes_found_so_far).
    """
    episodes: List[EpisodeMeta] = []
    seen: set[int] = set()

    for page_num in range(1, max_pages + 1):
        url = config.PODSCRIPTS_BASE_URL
        if page_num > 1:
            url = f"{url}?page={page_num}"

        try:
            resp = requests.get(url, timeout=30)
        except requests.RequestException:
            break
        if resp.status_code != 200:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=_EPISODE_LINK_RE)

        if not links:
            break

        found_new = False
        for link in links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if not text or not href:
                continue

            ep_num, guest, title = _parse_title(text)
            if ep_num == 0 or ep_num in seen:
                continue

            slug_match = _EPISODE_LINK_RE.search(href)
            slug = slug_match.group(0).split("/")[-1] if slug_match else ""

            full_url = f"https://podscripts.co{href}" if href.startswith("/") else href

            episodes.append(EpisodeMeta(
                number=ep_num,
                title=f"{guest} - {title}" if guest else title,
                guest=guest,
                slug=slug,
                url=full_url,
            ))
            seen.add(ep_num)
            found_new = True

        if progress_cb:
            progress_cb(page_num, len(episodes))

        if not found_new:
            break

        time.sleep(1)  # polite delay between listing pages

    episodes.sort(key=lambda e: e.number, reverse=True)
    return episodes


def get_episode_by_number(episode_number: int) -> Optional[EpisodeMeta]:
    """Find a single episode by number from the listing."""
    for ep in get_episode_list():
        if ep.number == episode_number:
            return ep
    return None


# ---------------------------------------------------------------------------
# Transcript scraping (Playwright – handles JS rendering)
# ---------------------------------------------------------------------------

def _new_browser_context(browser: Browser):
    """Create a browser context with a realistic user-agent."""
    return browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    )


def _scrape_single_page(browser: Browser, episode_url: str) -> str:
    """Scrape one transcript page using an existing browser instance."""
    context = _new_browser_context(browser)
    page = context.new_page()

    try:
        page.goto(episode_url, wait_until="networkidle", timeout=60_000)
    except PwTimeout:
        pass

    page.wait_for_timeout(3000)
    transcript_text = _extract_transcript(page)

    context.close()
    return transcript_text


def get_transcript(episode_url: str, headless: bool = True) -> str:
    """
    Open an episode page in a headless browser, wait for the transcript
    to render, and return the full transcript text.
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        transcript_text = _scrape_single_page(browser, episode_url)
        browser.close()

    if not transcript_text or len(transcript_text) < 200:
        raise RuntimeError(
            f"Could not extract transcript from {episode_url}. "
            "The page may require authentication or the transcript may not be available."
        )

    return transcript_text


def get_transcripts_batch(
    episodes: List[EpisodeMeta],
    *,
    headless: bool = True,
    delay: float = DEFAULT_SCRAPE_DELAY,
    on_success: Optional[Callable[[EpisodeMeta, str], None]] = None,
    on_error: Optional[Callable[[EpisodeMeta, Exception], None]] = None,
) -> Dict[int, str]:
    """
    Scrape transcripts for multiple episodes using a single browser instance.

    Args:
        episodes: List of episodes to scrape.
        headless: Run browser in headless mode.
        delay: Seconds to wait between page loads (rate limiting).
        on_success: Callback(episode, transcript) after each successful scrape.
        on_error: Callback(episode, exception) after each failed scrape.

    Returns:
        Dict mapping episode number → transcript text (only successes).
    """
    results: Dict[int, str] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)

        for i, ep in enumerate(episodes):
            try:
                transcript = _scrape_single_page(browser, ep.url)

                if not transcript or len(transcript) < 200:
                    raise RuntimeError(
                        "Transcript too short or empty — may require auth."
                    )

                results[ep.number] = transcript
                if on_success:
                    on_success(ep, transcript)

            except Exception as exc:
                if on_error:
                    on_error(ep, exc)

            # Rate-limit: wait between episodes (skip after last one)
            if i < len(episodes) - 1:
                time.sleep(delay)

        browser.close()

    return results


def _extract_transcript(page) -> str:
    """
    Try multiple CSS selector strategies to extract the transcript text
    from a podscripts.co episode page.
    """
    # Strategy 1: Look for common transcript container selectors
    selectors_to_try = [
        "div.transcript",
        "div[class*='transcript']",
        "div[class*='Transcript']",
        "section.transcript",
        "article.transcript",
        "#transcript",
        "div[data-testid='transcript']",
    ]

    for selector in selectors_to_try:
        elements = page.query_selector_all(selector)
        if elements:
            texts = [el.inner_text() for el in elements]
            combined = "\n".join(t.strip() for t in texts if t.strip())
            if len(combined) > 200:
                return combined

    # Strategy 2: Look for sentence-level elements (podscripts uses clickable sentences)
    sentence_selectors = [
        "span[class*='sentence']",
        "span[data-timestamp]",
        "p[class*='sentence']",
        "div[class*='sentence']",
        "span[class*='word']",
        "[class*='transcript'] span",
        "[class*='transcript'] p",
    ]

    for selector in sentence_selectors:
        elements = page.query_selector_all(selector)
        if len(elements) > 10:  # transcripts have many sentences
            texts = [el.inner_text() for el in elements]
            combined = " ".join(t.strip() for t in texts if t.strip())
            if len(combined) > 200:
                return combined

    # Strategy 3: Broad extraction – find the largest text block on the page
    # Exclude nav, header, footer, and other non-content elements
    page.evaluate("""
        () => {
            for (const tag of ['nav', 'header', 'footer', 'script', 'style']) {
                document.querySelectorAll(tag).forEach(el => el.remove());
            }
        }
    """)

    all_divs = page.query_selector_all("div, article, section")
    best_text = ""
    for div in all_divs:
        text = div.inner_text()
        if len(text) > len(best_text):
            best_text = text

    return best_text.strip()
