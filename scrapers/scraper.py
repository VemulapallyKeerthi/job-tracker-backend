"""
scraper.py — Combined job scraper for:
  Indeed, Dice, LinkedIn, Glassdoor

Fields sent to backend:
  title, company, location, status, source, url, description, posted_date

Usage:
  python scraper.py

Env vars:
  API_URL           — backend endpoint (default: http://127.0.0.1:8001/jobs)
  SEARCH_QUERIES    — comma-separated job titles (default: "software engineer,data scientist")
  SEARCH_LOCATIONS  — comma-separated locations  (default: "United States")
                      e.g. "Remote,New York NY,San Francisco CA,Seattle WA"
  HEADLESS          — true/false (default: true)
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import requests
import time
import os
import logging
import re
from datetime import date, timedelta

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
API_URL          = os.getenv("API_URL", "http://127.0.0.1:8001/jobs")
SEARCH_QUERIES   = [
    q.strip()
    for q in os.getenv("SEARCH_QUERIES", "software engineer,data scientist").split(",")
    if q.strip()
]
SEARCH_LOCATIONS = [
    loc.strip()
    for loc in os.getenv("SEARCH_LOCATIONS", "United States").split(",")
    if loc.strip()
]
HEADLESS    = os.getenv("HEADLESS", "true").lower() == "true"
MAX_RETRIES = 3

BROWSER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# ── Deduplication (within a single run) ──────────────────────────────────────
_seen: set[tuple[str, str]] = set()


# ── US Location Filter ────────────────────────────────────────────────────────
US_KEYWORDS = {
    "united states", "usa", "u.s.", "remote", "us remote",
    "new york", "san francisco", "seattle", "austin", "boston",
    "chicago", "los angeles", "denver", "atlanta", "dallas",
    "washington", "california", "texas", "new jersey", " ny",
    " ca", " wa", " tx", " dc", " ma", " il", " co", " ga",
    " fl", " nc", " va", " or", " az", " mn", " oh", " pa",
}

def is_us_location(location: str) -> bool:
    """Return True if location appears to be US-based or Remote."""
    if not location:
        return True  # no location = assume remote/US
    loc = location.lower()
    return any(kw in loc for kw in US_KEYWORDS)


# ── Date Parser ───────────────────────────────────────────────────────────────
def parse_relative_date(text: str) -> str:
    today = date.today()
    if not text:
        return today.isoformat()

    text = text.lower().strip()

    if any(w in text for w in ["just posted", "today", "just now", "new"]):
        return today.isoformat()

    match = re.search(r"(\d+)\+?\s*(day|week|month|hour)", text)
    if match:
        num  = int(match.group(1))
        unit = match.group(2)
        if unit == "hour":
            return today.isoformat()
        elif unit == "day":
            return (today - timedelta(days=num)).isoformat()
        elif unit == "week":
            return (today - timedelta(weeks=num)).isoformat()
        elif unit == "month":
            return (today - timedelta(days=num * 30)).isoformat()

    return today.isoformat()


# ── Helpers ───────────────────────────────────────────────────────────────────
def send_to_backend(job: dict) -> bool:
    """POST a job dict to the backend with retry + exponential backoff."""
    # ── US filter ──
    if not is_us_location(job.get("location", "")):
        log.debug(f"  ↷ Skipping non-US job: {job['title']} @ {job['location']}")
        return False

    # ── Parse posted_date from raw text or fallback to today ──
    raw_date = job.pop("posted_date_raw", None)
    if not job.get("posted_date"):
        job["posted_date"] = parse_relative_date(raw_date) if raw_date else date.today().isoformat()

    key = (job["title"].lower(), job["company"].lower())
    if key in _seen:
        log.debug(f"  ↷ Skipping duplicate: {job['title']} @ {job['company']}")
        return False
    _seen.add(key)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(API_URL, json=job, timeout=10)
            resp.raise_for_status()
            log.info(f"  ✓ Sent: [{job['source']}] {job['title']} @ {job['company']}")
            return True
        except requests.exceptions.RequestException as e:
            log.warning(f"  Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            time.sleep(2 ** attempt)
    log.error(f"  ✗ Failed after {MAX_RETRIES} attempts: {job.get('title')}")
    return False


def make_page(browser):
    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 800},
    )
    return context.new_page()


def safe_text(el) -> str:
    try:
        return el.inner_text().strip() if el else ""
    except Exception:
        return ""


def safe_attr(el, attr: str) -> str:
    try:
        return el.get_attribute(attr) or ""
    except Exception:
        return ""


def try_selectors(card, selectors: list[str]) -> str:
    for sel in selectors:
        try:
            el = card.query_selector(sel)
            if el:
                text = safe_text(el)
                if text:
                    return text
        except Exception:
            continue
    return ""


def wait_and_get_cards(page, selectors: list[str], timeout=8_000) -> list:
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=timeout)
            cards = page.query_selector_all(sel)
            if cards:
                log.info(f"  Selector '{sel}' matched {len(cards)} cards")
                return cards
        except PlaywrightTimeout:
            continue
    return []


def fetch_description(browser, job_url: str, selectors: list[str]) -> str:
    """
    Visit a job detail page and extract the full description text.

    Args:
        browser:   Playwright browser instance.
        job_url:   URL of the job detail page.
        selectors: List of CSS selectors to try for the description element.

    Returns:
        Description text, or empty string if not found.
    """
    if not job_url:
        return ""
    detail_page = make_page(browser)
    try:
        detail_page.goto(job_url, wait_until="domcontentloaded", timeout=20_000)
        # Wait for first matching selector
        for sel in selectors:
            try:
                detail_page.wait_for_selector(sel, timeout=6_000)
                el = detail_page.query_selector(sel)
                if el:
                    desc = safe_text(el)
                    if desc:
                        log.debug(f"  Description fetched ({len(desc)} chars)")
                        return desc
            except PlaywrightTimeout:
                continue
    except Exception as e:
        log.debug(f"  fetch_description failed for {job_url}: {e}")
    finally:
        detail_page.close()
        time.sleep(1)  # polite delay between detail page requests
    return ""


# ── Site scrapers ─────────────────────────────────────────────────────────────

def scrape_indeed(browser, location: str, query: str = SEARCH_QUERIES[0]) -> int:
    log.info(f"── Indeed [{location}] [{query}] ──────────────────────────")
    url = (
        f"https://www.indeed.com/jobs"
        f"?q={requests.utils.quote(query)}"
        f"&l={requests.utils.quote(location)}"
    )
    page = make_page(browser)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except PlaywrightTimeout:
        log.error("  Indeed: page load timed out")
        page.close()
        return 0

    cards = wait_and_get_cards(page, [
        "div.job_seen_beacon",
        "td.resultContent",
        "div.slider_container",
    ])
    if not cards:
        log.warning("  Indeed: no cards found — may be blocked")
        page.close()
        return 0

    sent = 0
    for card in cards:
        title         = try_selectors(card, ["h2 span[title]", "h2 span", "h2 a span"])
        company       = try_selectors(card, ["span[data-testid='company-name']", "span.companyName", "[class*='company']"])
        location_text = try_selectors(card, ["div[data-testid='text-location']", "div.companyLocation", "[class*='location']"])
        link_el       = card.query_selector("h2 a")
        href          = safe_attr(link_el, "href")
        job_url       = f"https://www.indeed.com{href}" if href.startswith("/") else href
        date_el       = card.query_selector("span.date, div[class*='date'], span[class*='posted']")
        raw_date      = safe_text(date_el)

        if not (title and company):
            continue

        # ── Fetch full description from detail page ──
        desc = fetch_description(browser, job_url, selectors=[
            "div#jobDescriptionText",
            "div[id*='jobDescription']",
            "div.jobsearch-jobDescriptionText",
            "div[class*='jobDescription']",
        ])

        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "indeed",
            "url": job_url, "description": desc,
            "posted_date_raw": raw_date,
        }
        if send_to_backend(job):
            sent += 1

    page.close()
    return sent


def scrape_dice(browser, location: str, query: str = SEARCH_QUERIES[0]) -> int:
    log.info(f"── Dice [{location}] [{query}] ────────────────────────────")
    url = (
        f"https://www.dice.com/jobs"
        f"?q={requests.utils.quote(query)}"
        f"&location={requests.utils.quote(location)}"
        f"&radius=30&radiusUnit=mi&page=1&pageSize=20"
        f"&filters.postedDate=ONE_DAY"
    )
    page = make_page(browser)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        time.sleep(3)  # Dice is JS-heavy — wait for cards to render
    except PlaywrightTimeout:
        log.error("  Dice: page load timed out")
        page.close()
        return 0

    cards = wait_and_get_cards(page, [
        "dhi-search-card",
        "div[data-cy='search-result']",
        "div.card",
        "li.results-card",
    ], timeout=10_000)
    if not cards:
        log.warning("  Dice: no cards found")
        page.close()
        return 0

    sent = 0
    for card in cards:
        title         = try_selectors(card, [
            "a[data-cy='card-title-link']",
            "h5 a", "a.card-title-link",
            "[data-cy='card-title']", "h6 a",
        ])
        company       = try_selectors(card, [
            "a[data-cy='search-result-company-name']",
            "span[data-cy='search-result-company-name']",
            "a.employer-name", "[class*='company']",
        ])
        location_text = try_selectors(card, [
            "span[data-cy='search-result-location']",
            "span.search-result-location",
            "[class*='location']",
        ])
        link_el  = card.query_selector("a[data-cy='card-title-link'], a.card-title-link, h5 a")
        href     = safe_attr(link_el, "href")
        job_url  = f"https://www.dice.com{href}" if href.startswith("/") else href
        date_el  = card.query_selector("span[data-cy='card-posted-date'], span[class*='posted'], div[class*='date']")
        raw_date = safe_text(date_el)

        if not (title and company):
            continue

        # ── Fetch full description from detail page ──
        desc = fetch_description(browser, job_url, selectors=[
            "div[data-testid='jobDescriptionHtml']",
            "div.job-description",
            "div[class*='jobDescription']",
            "section[class*='description']",
            "div#jobDescription",
        ])

        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "dice",
            "url": job_url, "description": desc,
            "posted_date_raw": raw_date,
        }
        if send_to_backend(job):
            sent += 1

    page.close()
    return sent


def scrape_linkedin(browser, location: str, query: str = SEARCH_QUERIES[0]) -> int:
    log.info(f"── LinkedIn [{location}] [{query}] ────────────────────────")
    url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={requests.utils.quote(query)}"
        f"&location={requests.utils.quote(location)}"
        f"&f_TPR=r86400"
    )
    page = make_page(browser)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except PlaywrightTimeout:
        log.error("  LinkedIn: page load timed out")
        page.close()
        return 0

    cards = wait_and_get_cards(page, [
        "div.base-card",
        "li.jobs-search-results__list-item",
        "div[class*='job-search-card']",
    ])
    if not cards:
        log.warning("  LinkedIn: no cards found — may require login or rate limited")
        page.close()
        return 0

    sent = 0
    for card in cards:
        title         = try_selectors(card, ["h3.base-search-card__title", "span[class*='title']", "h3 a"])
        company       = try_selectors(card, ["h4.base-search-card__subtitle", "a[class*='company']", "span[class*='company']"])
        location_text = try_selectors(card, ["span.job-search-card__location", "span[class*='location']"])
        link_el       = card.query_selector("a.base-card__full-link, a[class*='job-card']")
        job_url       = safe_attr(link_el, "href").split("?")[0]
        date_el       = card.query_selector("time, span[class*='listdate'], span[class*='posted-date']")
        raw_date      = safe_text(date_el) or (safe_attr(date_el, "datetime") if date_el else "")

        if not (title and company):
            continue

        # ── Fetch full description from detail page ──
        desc = fetch_description(browser, job_url, selectors=[
            "div.show-more-less-html__markup",
            "div[class*='description__text']",
            "section.show-more-less-html",
            "div[class*='job-description']",
        ])

        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "linkedin",
            "url": job_url, "description": desc,
            "posted_date_raw": raw_date,
        }
        if send_to_backend(job):
            sent += 1

    page.close()
    return sent


def scrape_glassdoor(browser, location: str, query: str = SEARCH_QUERIES[0]) -> int:
    log.info(f"── Glassdoor [{location}] [{query}] ───────────────────────")
    url = (
        f"https://www.glassdoor.com/Job/jobs.htm"
        f"?sc.keyword={requests.utils.quote(query)}"
        f"&locT=N&locId=1"
        f"&fromAge=1"
    )
    page = make_page(browser)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        time.sleep(2)
    except PlaywrightTimeout:
        log.error("  Glassdoor: page load timed out")
        page.close()
        return 0

    cards = wait_and_get_cards(page, [
        "li[data-test='jobListing']",
        "article[class*='JobCard']",
        "div[class*='jobCard']",
    ], timeout=10_000)
    if not cards:
        log.warning("  Glassdoor: no cards found — may require login")
        page.close()
        return 0

    sent = 0
    for card in cards:
        title         = try_selectors(card, [
            "a.JobCard_jobTitle__GLyJ1",
            "a[data-test='job-title']",
            "div[class*='JobCard_jobTitle']",
            "a[class*='jobTitle']",
            "span[class*='title']",
        ])
        company       = try_selectors(card, [
            "div.EmployerProfile_employerInfo__BGtLN span",
            "span[class*='EmployerProfile_compactEmployerName']",
            "span[class*='EmployerProfile_employerName']",
            "div[class*='JobCard_soc'] span",
            "span[class*='employer']",
        ])
        location_text = try_selectors(card, [
            "div[class*='JobCard_location']",
            "span[class*='location']",
            "div[class*='location']",
        ])
        link_el  = card.query_selector("a.JobCard_jobTitle__GLyJ1, a[data-test='job-title'], a[class*='jobTitle']")
        href     = safe_attr(link_el, "href")
        job_url  = f"https://www.glassdoor.com{href}" if href.startswith("/") else href
        date_el  = card.query_selector("div[class*='JobCard_jobAgeItem'], span[class*='JobCard_jobAge'], div[class*='age']")
        raw_date = safe_text(date_el)

        if not (title and company):
            continue

        # ── Fetch full description from detail page ──
        desc = fetch_description(browser, job_url, selectors=[
            "div[class*='JobDetails_jobDescription']",
            "div[class*='jobDescriptionContent']",
            "div[id='JobDescriptionContainer']",
            "div[class*='desc']",
        ])

        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "glassdoor",
            "url": job_url, "description": desc,
            "posted_date_raw": raw_date,
        }
        if send_to_backend(job):
            sent += 1

    page.close()
    return sent


# ── Main runner ───────────────────────────────────────────────────────────────
SCRAPERS = {
    "indeed":    scrape_indeed,
    "dice":      scrape_dice,
    "linkedin":  scrape_linkedin,
    "glassdoor": scrape_glassdoor,
}


def run_all():
    log.info("=" * 55)
    log.info(f"Queries:   {SEARCH_QUERIES}")
    log.info(f"Locations: {SEARCH_LOCATIONS}")
    log.info(f"Backend:   {API_URL} | Headless: {HEADLESS}")
    log.info("=" * 55)

    totals: dict[str, int] = {name: 0 for name in SCRAPERS}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, args=BROWSER_ARGS)

        for query in SEARCH_QUERIES:
            log.info(f"\n🔍 Query: {query}")
            log.info("=" * 55)

            for location in SEARCH_LOCATIONS:
                log.info(f"\n📍 Location: {location}")
                log.info("-" * 55)

                for name, scraper_fn in SCRAPERS.items():
                    try:
                        count = scraper_fn(browser, location, query)
                        totals[name] += count
                    except Exception as e:
                        log.error(f"  {name}: unexpected error — {e}")
                    time.sleep(2)

        browser.close()

    log.info("\n" + "=" * 55)
    log.info("SUMMARY")
    log.info(f"  Queries:           {len(SEARCH_QUERIES)}")
    log.info(f"  Locations:         {len(SEARCH_LOCATIONS)}")
    log.info(f"  Unique jobs sent:  {sum(totals.values())}")
    log.info(f"  Duplicates skipped:{len(_seen) - sum(totals.values())}")
    for name, count in totals.items():
        log.info(f"  {name:<12} {count} jobs")
    log.info("=" * 55)


if __name__ == "__main__":
    run_all()