"""
scraper.py — Combined job scraper for:
  Indeed, Dice, Handshake, LinkedIn, Wellfound, Glassdoor

Fields sent to backend:
  title, company, location, status, source, url, description

Usage:
  python scraper.py

Env vars:
  API_URL           — backend endpoint (default: http://127.0.0.1:8001/jobs)
  SEARCH_QUERY      — job search term   (default: "software engineer")
  SEARCH_LOCATIONS  — comma-separated locations (default: "United States")
                      e.g. "Remote,New York NY,San Francisco CA,Seattle WA"
  HEADLESS          — true/false         (default: true)
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import requests
import time
import os
import logging

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
HEADLESS     = os.getenv("HEADLESS", "true").lower() == "true"
MAX_RETRIES  = 3

BROWSER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# ── Deduplication (within a single run) ──────────────────────────────────────
# Tracks (title, company) pairs already sent this session to avoid duplicates
# across multiple locations
_seen: set[tuple[str, str]] = set()


# ── Helpers ───────────────────────────────────────────────────────────────────
def send_to_backend(job: dict) -> bool:
    """POST a job dict to the backend with retry + exponential backoff."""
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


# ── Site scrapers (each accepts browser + location) ───────────────────────────

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
        title    = try_selectors(card, ["h2 span[title]", "h2 span", "h2 a span"])
        company  = try_selectors(card, ["span[data-testid='company-name']", "span.companyName", "[class*='company']"])
        location_text = try_selectors(card, ["div[data-testid='text-location']", "div.companyLocation", "[class*='location']"])
        link_el  = card.query_selector("h2 a")
        href     = safe_attr(link_el, "href")
        job_url  = f"https://www.indeed.com{href}" if href.startswith("/") else href
        desc_el  = card.query_selector("div.job-snippet, div[class*='snippet']")
        desc     = safe_text(desc_el)

        if not (title and company):
            continue
        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "indeed",
            "url": job_url, "description": desc,
        }
        if send_to_backend(job):
            sent += 1

    page.close()
    return sent


def scrape_dice(browser, location: str, query: str = SEARCH_QUERIES[0]) -> int:
    log.info(f"── Dice [{location}] [{query}] ────────────────────────────")
    url = (
        f"https://www.dice.com/jobs?q={requests.utils.quote(query)}"
        f"&location={requests.utils.quote(location)}&radius=30&radiusUnit=mi&page=1&pageSize=20"
    )
    page = make_page(browser)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except PlaywrightTimeout:
        log.error("  Dice: page load timed out")
        page.close()
        return 0

    cards = wait_and_get_cards(page, [
        "dhi-search-card",
        "div[data-cy='search-result']",
        "div.card-shadow",
    ])
    if not cards:
        log.warning("  Dice: no cards found")
        page.close()
        return 0

    sent = 0
    for card in cards:
        title    = try_selectors(card, ["a.card-title-link", "h5 a", "[data-cy='card-title']"])
        company  = try_selectors(card, ["a.employer-name", "span[data-cy='search-result-company-name']", "[class*='company']"])
        location_text = try_selectors(card, ["span[data-cy='search-result-location']", "span.search-result-location", "[class*='location']"])
        link_el  = card.query_selector("a.card-title-link, h5 a")
        href     = safe_attr(link_el, "href")
        job_url  = f"https://www.dice.com{href}" if href.startswith("/") else href
        desc_el  = card.query_selector("div[data-cy='card-summary'], p.card-description")
        desc     = safe_text(desc_el)

        if not (title and company):
            continue
        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "dice",
            "url": job_url, "description": desc,
        }
        if send_to_backend(job):
            sent += 1

    page.close()
    return sent


def scrape_handshake(browser, location: str, query: str = SEARCH_QUERIES[0]) -> int:
    log.info(f"── Handshake [{location}] [{query}] ───────────────────────")
    url = (
        f"https://app.joinhandshake.com/stu/postings"
        f"?page=1&per_page=25&sort_direction=desc&sort_column=default"
        f"&query={requests.utils.quote(query)}"
    )
    page = make_page(browser)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except PlaywrightTimeout:
        log.error("  Handshake: page load timed out")
        page.close()
        return 0

    if "sign_in" in page.url or "login" in page.url:
        log.warning("  Handshake: login required — skipping")
        page.close()
        return 0

    cards = wait_and_get_cards(page, [
        "li[data-hook='jobs-card']",
        "div[class*='JobCard']",
        "div[class*='posting-card']",
    ])
    if not cards:
        log.warning("  Handshake: no cards found")
        page.close()
        return 0

    sent = 0
    for card in cards:
        title    = try_selectors(card, ["span[class*='title']", "h3", "a[class*='title']"])
        company  = try_selectors(card, ["span[class*='employer']", "span[class*='company']", "p[class*='employer']"])
        location_text = try_selectors(card, ["span[class*='location']", "div[class*='location']"])
        link_el  = card.query_selector("a")
        href     = safe_attr(link_el, "href")
        job_url  = f"https://app.joinhandshake.com{href}" if href.startswith("/") else href
        desc_el  = card.query_selector("p[class*='description'], div[class*='description']")
        desc     = safe_text(desc_el)

        if not (title and company):
            continue
        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "handshake",
            "url": job_url, "description": desc,
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
        title    = try_selectors(card, ["h3.base-search-card__title", "span[class*='title']", "h3 a"])
        company  = try_selectors(card, ["h4.base-search-card__subtitle", "a[class*='company']", "span[class*='company']"])
        location_text = try_selectors(card, ["span.job-search-card__location", "span[class*='location']"])
        link_el  = card.query_selector("a.base-card__full-link, a[class*='job-card']")
        job_url  = safe_attr(link_el, "href").split("?")[0]
        desc_el  = card.query_selector("p[class*='description'], div[class*='description']")
        desc     = safe_text(desc_el)

        if not (title and company):
            continue
        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "linkedin",
            "url": job_url, "description": desc,
        }
        if send_to_backend(job):
            sent += 1

    page.close()
    return sent


def scrape_wellfound(browser, location: str, query: str = SEARCH_QUERIES[0]) -> int:
    log.info(f"── Wellfound [{location}] [{query}] ───────────────────────")
    # Wellfound doesn't support location in URL — scrapes globally
    url = f"https://wellfound.com/jobs?q={requests.utils.quote(query)}"
    page = make_page(browser)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except PlaywrightTimeout:
        log.error("  Wellfound: page load timed out")
        page.close()
        return 0

    cards = wait_and_get_cards(page, [
        "div[class*='JobListingCard']",
        "div[data-test='JobListing']",
        "div[class*='styles_component']",
    ])
    if not cards:
        log.warning("  Wellfound: no cards found")
        page.close()
        return 0

    sent = 0
    for card in cards:
        title    = try_selectors(card, ["a[class*='title']", "h2", "span[class*='title']"])
        company  = try_selectors(card, ["a[class*='startup']", "span[class*='company']", "h3"])
        location_text = try_selectors(card, ["span[class*='location']", "div[class*='location']"])
        link_el  = card.query_selector("a[href*='/jobs/']")
        href     = safe_attr(link_el, "href")
        job_url  = f"https://wellfound.com{href}" if href.startswith("/") else href
        desc_el  = card.query_selector("div[class*='description'], p[class*='description']")
        desc     = safe_text(desc_el)

        if not (title and company):
            continue
        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "wellfound",
            "url": job_url, "description": desc,
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
    )
    page = make_page(browser)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except PlaywrightTimeout:
        log.error("  Glassdoor: page load timed out")
        page.close()
        return 0

    cards = wait_and_get_cards(page, [
        "li[data-test='jobListing']",
        "article[class*='JobCard']",
        "div[class*='jobCard']",
    ])
    if not cards:
        log.warning("  Glassdoor: no cards found — may require login")
        page.close()
        return 0

    sent = 0
    for card in cards:
        title    = try_selectors(card, ["a[data-test='job-title']", "div[class*='JobCard_jobTitle']", "span[class*='title']"])
        company  = try_selectors(card, ["span[class*='EmployerProfile_employerName']", "div[class*='JobCard_soc']", "span[class*='company']"])
        location_text = try_selectors(card, ["div[class*='JobCard_location']", "span[class*='location']"])
        link_el  = card.query_selector("a[data-test='job-title'], a[class*='jobTitle']")
        href     = safe_attr(link_el, "href")
        job_url  = f"https://www.glassdoor.com{href}" if href.startswith("/") else href
        desc_el  = card.query_selector("div[class*='jobDescriptionContent'], div[class*='description']")
        desc     = safe_text(desc_el)

        if not (title and company):
            continue
        job = {
            "title": title, "company": company, "location": location_text,
            "status": "saved", "source": "glassdoor",
            "url": job_url, "description": desc,
        }
        if send_to_backend(job):
            sent += 1

    page.close()
    return sent


# ── Main runner ───────────────────────────────────────────────────────────────
SCRAPERS = {
    "indeed":    scrape_indeed,
    "dice":      scrape_dice,
    "handshake": scrape_handshake,
    "linkedin":  scrape_linkedin,
    "wellfound": scrape_wellfound,
    "glassdoor": scrape_glassdoor,
}

# Sites that don't support location filtering (run only once regardless of locations)
LOCATION_INDEPENDENT = {"wellfound", "handshake"}


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
                    # Location-independent sites only run once per query
                    if name in LOCATION_INDEPENDENT and location != SEARCH_LOCATIONS[0]:
                        log.info(f"  {name}: skipping (location-independent, already scraped)")
                        continue
                    try:
                        # Pass current query to each scraper
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
    log.info(f"  Duplicates skip:   {len(_seen) - sum(totals.values())}")
    for name, count in totals.items():
        log.info(f"  {name:<12} {count} jobs")
    log.info("=" * 55)


if __name__ == "__main__":
    run_all()