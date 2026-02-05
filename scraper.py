import sqlite3
import os
import re
import logging
import time
from abc import ABC, abstractmethod
from playwright.sync_api import sync_playwright

# --- LOGGING & DATABASE SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[logging.FileHandler("scraper.log"), logging.StreamHandler()]
)

class DatabaseManager:
    def __init__(self, db_name="scraped_data.db"):
        self.db_name = db_name
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    base_url TEXT,
                    course_name TEXT,
                    cta_link TEXT,
                    price TEXT,
                    pdp_price TEXT,
                    cta_status TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    def save_batch(self, courses):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            new_items = 0
            for item in courses:
                cursor.execute('SELECT id FROM courses WHERE course_name = ? AND cta_link = ?', (item['course_name'], item['cta_link']))
                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO courses (base_url, course_name, cta_link, price, pdp_price, cta_status) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (item['base_url'], item['course_name'], item['cta_link'], item['price'], item.get('pdp_price', 'N/A'), item.get('cta_status', 'N/A')))
                    new_items += 1
            conn.commit()
            if new_items > 0:
                logging.info(f"Successfully saved {new_items} new courses.")

# --- BASE HANDLER STRATEGY ---
class BasePageHandler(ABC):
    """Abstract base class for all page-specific scraping logic."""
    
    def __init__(self, page, db_manager):
        self.page = page
        self.db = db_manager
        self.processed_keys = set()

    @abstractmethod
    def can_handle(url: str) -> bool:
        """Determines if this handler is suitable for the given URL."""
        pass

    @abstractmethod
    def scrape(self, url: str):
        """High-level scraping workflow for the page."""
        pass

    def safe_get_text(self, container, selectors):
        """Utility to try multiple selectors and return the first found text."""
        for sel in selectors:
            loc = container.locator(sel)
            if loc.count() > 0:
                text = loc.first.inner_text().strip().replace('\n', ' ')
                if text: return text
        return "N/A"

    def extract_cta_link(self, card, tab_el=None, tab_text="Default"):
        """Standard logic to find a link: Href first, then Click-and-Back."""
        # 1. Look for direct links
        links = card.locator('xpath=self::a | .//a')
        for i in range(links.count()):
            href = links.nth(i).get_attribute('href')
            if href and not href.startswith('#') and 'javascript' not in href:
                return f"https://allen.in{href}" if href.startswith('/') else href

        # 2. Click and Capture logic
        cta = card.locator('button')
        if cta.count() > 0:
            current_url = self.page.url
            try:
                cta.first.scroll_into_view_if_needed()
                cta.first.evaluate("el => el.click()")
                
                # Wait for URL to change
                start = time.time()
                while time.time() - start < 8:
                    if self.page.evaluate("window.location.href") != current_url:
                        break
                    time.sleep(0.5)
                
                final_link = self.page.evaluate("window.location.href")
                
                # Restoration
                if final_link != current_url:
                    self.page.go_back(wait_until="domcontentloaded")
                    if tab_el:
                        tab_el.evaluate("el => el.click()")
                        time.sleep(2)
                return final_link
            except Exception as e:
                logging.warning(f"Failed to capture link via click: {e}")
        return self.page.url

    def verify_pdp(self, pdp_url, original_url):
        """Navigates to the PDP and returns found price and CTA status."""
        if not pdp_url or pdp_url == original_url:
            return "N/A", "N/A"
            
        try:
            logging.info(f"     Verifying PDP: {pdp_url}")
            self.page.goto(pdp_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            
            # Look for Price (₹ symbol)
            pdp_price = "Not Found"
            # Prioritize heading elements or common price locations
            price_locators = [
                'h2:has-text("₹")',
                'span:has-text("₹")',
                'p:has-text("₹")',
                'div:has-text("₹")'
            ]
            for sel in price_locators:
                loc = self.page.locator(sel)
                for i in range(loc.count()):
                    text = loc.nth(i).inner_text().strip()
                    if '₹' in text and len(text) < 25:
                        pdp_price = text
                        break
                if pdp_price != "Not Found": break
                
            # Look for CTA
            cta_status = "Not Found"
            cta_keywords = ["enroll now", "enrol now", "buy now"]
            buttons = self.page.locator('button, a').all()
            for btn in buttons:
                try:
                    text = btn.inner_text().strip().lower()
                    if any(kw == text or (kw in text and len(text) < 20) for kw in cta_keywords):
                        cta_status = f"Found ({btn.inner_text().strip()})"
                        break
                except: continue
            
            # Navigate back to original context
            self.page.goto(original_url, wait_until="domcontentloaded")
            return pdp_price, cta_status
        except Exception as e:
            logging.warning(f"     PDP verification failed: {e}")
            try: self.page.goto(original_url, wait_until="domcontentloaded") # Attempt recovery
            except: pass
            return "Error", "Error"

# --- SPECIALIZED HANDLER: Homepage ---
class HomepageHandler(BasePageHandler):
    @staticmethod
    def can_handle(url):
        return url.strip('/') == "https://allen.in"

    def scrape(self, url):
        logging.info(f"Using HomepageHandler for {url}")
        self.page.goto(url, wait_until="domcontentloaded")
        time.sleep(3)
        
        # Identify Tabs (JEE, NEET, etc.)
        tab_loc = self.page.locator('div[data-testid*="TAB_ITEM"]')
        tabs = []
        for t in tab_loc.all():
            txt = t.inner_text().strip()
            if txt in ['JEE', 'NEET', 'Classes 6-10']:
                tabs.append((t, txt))

        for tab_el, tab_name in (tabs if tabs else [(None, "Main")]):
            logging.info(f"--- Category: {tab_name} ---")
            if tab_el:
                tab_el.evaluate("el => el.click()")
                time.sleep(2)

            # Homepage cards are div-based
            cards = self.page.locator('div.rounded-normal.flex.flex-col')
            scraped_batch = []
            
            for i in range(cards.count()):
                card = cards.nth(i)
                name = self.safe_get_text(card, ['h2', 'p.font-semibold'])
                
                if name == "N/A" or f"{tab_name}_{name}" in self.processed_keys: continue
                self.processed_keys.add(f"{tab_name}_{name}")

                logging.info(f"  -> {name}")
                link = self.extract_cta_link(card, tab_el, tab_name)
                logging.info(f"     Listing URL: {link}")
                
                # Verify PDP
                pdp_price, cta_status = self.verify_pdp(link, url)
                if tab_el: # Restore tab state
                    tab_el.evaluate("el => el.click()")
                    time.sleep(1)
                
                logging.info(f"     PDP Price: {pdp_price} | CTA: {cta_status}")

                scraped_batch.append({
                    "base_url": url, 
                    "course_name": name, 
                    "cta_link": link, 
                    "price": self.safe_get_text(card, ['[class*="price"]', '[class*="fee"]']),
                    "pdp_price": pdp_price,
                    "cta_status": cta_status
                })
            
            self.db.save_batch(scraped_batch)

# --- SPECIALIZED HANDLER: Course Details Page ---
class CourseDetailsHandler(BasePageHandler):
    @staticmethod
    def can_handle(url):
        return "/online-coaching-" in url or ("/neet/" in url and url.strip('/') != "https://allen.in")

    def scrape(self, url):
        logging.info(f"Using CourseDetailsHandler for {url}")
        self.page.goto(url, wait_until="domcontentloaded")
        time.sleep(3)

        # Filters/Pills (Live, Recorded)
        pills = self.page.locator('button').filter(
            has_text=re.compile(r'^(Live|Recorded|Online Test Series|Offline Test Series)$')
        ).all()

        for pill in (pills if pills else [None]):
            pill_name = pill.inner_text().strip() if pill else "Default"
            logging.info(f"--- Filter: {pill_name} ---")
            if pill:
                pill.evaluate("el => el.click()")
                time.sleep(2)

            # Details page cards are li-based
            cards = self.page.locator('li[data-testid^="card-"]')
            scraped_batch = []

            for i in range(cards.count()):
                card = cards.nth(i)
                name = self.safe_get_text(card, ['p.font-semibold', 'h2', 'p'])
                
                if name == "N/A" or f"{pill_name}_{name}" in self.processed_keys: continue
                self.processed_keys.add(f"{pill_name}_{name}")

                logging.info(f"  -> {name}")
                link = self.extract_cta_link(card, pill, pill_name)
                logging.info(f"     Listing URL: {link}")

                # Verify PDP
                pdp_price, cta_status = self.verify_pdp(link, url)
                if pill: # Restore pill state
                    pill.evaluate("el => el.click()")
                    time.sleep(1)
                
                logging.info(f"     PDP Price: {pdp_price} | CTA: {cta_status}")

                scraped_batch.append({
                    "base_url": url, 
                    "course_name": name, 
                    "cta_link": link, 
                    "price": self.safe_get_text(card, ['[class*="price"]', '[class*="fee"]']),
                    "pdp_price": pdp_price,
                    "cta_status": cta_status
                })
            
            self.db.save_batch(scraped_batch)

# --- CORE ENGINE ---
class ScraperEngine:
    def __init__(self, urls_file="urls.txt"):
        self.urls_file = urls_file
        self.db = DatabaseManager()
        self.handlers = [HomepageHandler, CourseDetailsHandler] # Order matters

    def run(self):
        if not os.path.exists(self.urls_file):
            logging.error(f"URL file {self.urls_file} missing.")
            return

        with open(self.urls_file, "r") as f:
            urls = [line.strip() for line in f if line.strip()]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_viewport_size({"width": 1920, "height": 1080})

            for url in urls:
                # Dispatcher: Select the correct handler
                handler_class = None
                for hc in self.handlers:
                    if hc.can_handle(url):
                        handler_class = hc
                        break
                
                if handler_class:
                    handler = handler_class(page, self.db)
                    try:
                        handler.scrape(url)
                    except Exception as e:
                        logging.error(f"Error scraping {url}: {e}")
                else:
                    logging.warning(f"No handler found for URL: {url}")

            browser.close()

if __name__ == "__main__":
    engine = ScraperEngine()
    engine.run()
