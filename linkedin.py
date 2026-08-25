import hashlib
import logging
import re
from urllib.parse import urlencode

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

import config
from filters import parse_posted_at

logger = logging.getLogger(__name__)

LINKEDIN_SEARCH_BASE = "https://www.linkedin.com/jobs/search/"
JOB_VIEW_BASE = "https://www.linkedin.com/jobs/view/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

BLOCK_HINTS = (
    "authwall",
    "checkpoint",
    "unusual traffic",
    "are you a robot",
    "security check",
    "suspicious activity",
)


class LinkedInAccessError(Exception):
    """Raised when LinkedIn cannot be read (login wall, block, network, etc.)."""


def build_search_url(keywords, location):
    params = {}
    if keywords:
        params["keywords"] = keywords
    if location:
        params["location"] = location
    return f"{LINKEDIN_SEARCH_BASE}?{urlencode(params)}"


def derive_linkedin_id(raw_id, url):
    """Return a stable unique id. Prefer LinkedIn's job id, else a hash of the URL."""
    if raw_id:
        text = str(raw_id).strip()
        match = re.search(r"(\d{8,})", text)
        if match:
            return match.group(1)
        if text:
            return text[:64]

    if url:
        match = re.search(r"/jobs/view/(?:[\w-]+-)?(\d{8,})", url)
        if match:
            return match.group(1)
        match = re.search(r"[?&]currentJobId=(\d+)", url)
        if match:
            return match.group(1)
        canonical = url.split("?")[0].strip()
        if canonical:
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    return hashlib.sha256(f"{raw_id}|{url}".encode("utf-8")).hexdigest()[:32]


def detect_remote_type(location, extra_text=""):
    """Only set remote_type when the listing explicitly mentions it."""
    text = f"{location or ''} {extra_text or ''}".lower()
    if re.search(r"\bhybrid\b", text):
        return "hybrid"
    if re.search(r"\bremote\b", text):
        return "remote"
    if re.search(r"\bon[- ]?site\b", text) or re.search(r"\bonsite\b", text):
        return "on-site"
    return None


def normalize_job(raw, search):
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or "").strip()
    location = (raw.get("location") or "").strip()
    url = (raw.get("url") or "").strip()
    posted_text = (raw.get("posted_text") or "").strip() or None
    linkedin_id = derive_linkedin_id(raw.get("linkedin_id"), url)

    if url.startswith("/"):
        url = "https://www.linkedin.com" + url
    if linkedin_id.isdigit():
        url = f"{JOB_VIEW_BASE}{linkedin_id}"

    extra = " ".join(
        filter(
            None,
            [
                raw.get("workplace"),
                raw.get("employment_type"),
                posted_text,
            ],
        )
    )

    return {
        "linkedin_id": linkedin_id,
        "title": title or "Untitled job",
        "company": company,
        "location": location,
        "url": url,
        "description": (raw.get("description") or "").strip() or None,
        "posted_text": posted_text,
        "posted_at": parse_posted_at(posted_text, datetime_value=raw.get("posted_datetime")),
        "employment_type": (raw.get("employment_type") or "").strip() or None,
        "experience_level": (raw.get("experience_level") or "").strip() or None,
        "remote_type": detect_remote_type(location, extra),
        "search_name": getattr(search, "name", None) or raw.get("search_name"),
        "search_id": getattr(search, "id", None),
    }


def _inner_text(element):
    if element is None:
        return ""
    try:
        text = (element.inner_text() or "").strip()
    except Exception:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return text


def _first_text(card, selectors):
    for selector in selectors:
        text = _inner_text(card.query_selector(selector))
        if text:
            return text
    return ""


def _raise_if_blocked(page):
    current_url = (page.url or "").lower()
    if "authwall" in current_url or "/checkpoint/" in current_url:
        raise LinkedInAccessError("Unable to access LinkedIn")

    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        body = ""

    for hint in BLOCK_HINTS:
        if hint in current_url or hint in body:
            raise LinkedInAccessError("Unable to access LinkedIn")


def _scroll_for_jobs(page):
    for _ in range(4):
        cards = page.query_selector_all(
            "div.job-search-card, div.base-search-card, li.jobs-search-results__list-item"
        )
        if len(cards) >= config.MAX_JOBS_PER_SEARCH:
            break
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            break
        page.wait_for_timeout(800)


def _extract_card(card):
    urn = card.get_attribute("data-entity-urn") or card.get_attribute("data-job-id") or ""
    link = card.query_selector("a.base-card__full-link, a.job-card-list__title, a.base-card__link, a")
    href = ""
    if link:
        href = link.get_attribute("href") or ""

    title = _first_text(
        card,
        [
            "h3.base-search-card__title",
            ".job-card-list__title",
            ".base-search-card__title",
            "h3",
        ],
    )
    company = _first_text(
        card,
        [
            "h4.base-search-card__subtitle",
            ".base-search-card__subtitle",
            ".job-card-container__primary-description",
            "h4",
        ],
    )
    location = _first_text(
        card,
        [
            ".job-search-card__location",
            ".job-search-card__metadata-item",
            ".job-card-container__metadata-item",
        ],
    )
    time_el = card.query_selector("time")
    posted_text = _inner_text(time_el)
    posted_datetime = ""
    if time_el:
        posted_datetime = (time_el.get_attribute("datetime") or "").strip()
    if not posted_text:
        posted_text = posted_datetime

    workplace = _inner_text(
        card.query_selector(".job-search-card__benefits, .job-card-container__metadata-wrapper")
    )

    return {
        "linkedin_id": urn,
        "title": title,
        "company": company,
        "location": location,
        "url": href,
        "posted_text": posted_text,
        "posted_datetime": posted_datetime,
        "workplace": workplace,
        "description": None,
        "employment_type": None,
        "experience_level": None,
    }


def fetch_jobs(search):
    """Open a LinkedIn job search page and return normalized job dicts."""
    search_name = getattr(search, "name", "search")
    keywords = getattr(search, "keywords", "")
    location = getattr(search, "location", "")
    url = build_search_url(keywords, location)
    logger.info("Search started: %s", search_name)

    jobs = []
    seen = set()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=config.HEADLESS)
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                _raise_if_blocked(page)

                try:
                    page.wait_for_selector(
                        "div.job-search-card, div.base-search-card, "
                        "li.jobs-search-results__list-item, div.base-card",
                        timeout=15000,
                    )
                except PlaywrightTimeout:
                    _raise_if_blocked(page)
                    logger.info("Number of jobs found for '%s': 0", search_name)
                    return []

                _scroll_for_jobs(page)
                cards = page.query_selector_all(
                    "div.job-search-card, div.base-search-card"
                )
                if not cards:
                    cards = page.query_selector_all("div.base-card.relative, div.base-card")

                for card in cards[: config.MAX_JOBS_PER_SEARCH]:
                    try:
                        raw = _extract_card(card)
                        if not raw.get("title") and not raw.get("url"):
                            continue
                        job = normalize_job(raw, search)
                        if job["linkedin_id"] in seen:
                            continue
                        seen.add(job["linkedin_id"])
                        jobs.append(job)
                    except Exception:
                        logger.exception("Failed to parse a job card, skipping it")
            finally:
                context.close()
                browser.close()
    except LinkedInAccessError:
        logger.error("LinkedIn access error for search '%s'", search_name)
        raise
    except PlaywrightTimeout as exc:
        logger.error("LinkedIn access error for search '%s': timeout", search_name)
        raise LinkedInAccessError("Unable to access LinkedIn") from exc
    except Exception as exc:
        logger.error("LinkedIn access error for search '%s': %s", search_name, exc)
        raise LinkedInAccessError("Unable to access LinkedIn") from exc

    logger.info("Number of jobs found for '%s': %s", search_name, len(jobs))
    return jobs
