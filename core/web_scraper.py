"""
Module de web scraping pour extraire du contenu depuis des URLs
Équivalent Python du WebCrawler Java avec des améliorations

Supporte:
- Extraction de texte depuis des pages web (Playwright + BeautifulSoup)
- Téléchargement et extraction de texte depuis des PDFs
- Validation d'URLs
- Gestion des erreurs et timeouts
- Authentification (login + captcha) pour les pages protégées
- Pool de navigateurs persistant (évite le relancement à chaque URL)
- Nettoyage de texte spécifique par domaine
"""

import logging
import queue
import re
import tempfile
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .media_config import Media, MediaConfig

# Configuration du logger
logger = logging.getLogger(__name__)


class PlaywrightRunner:
    """
    Runs Playwright sync API calls on one dedicated thread. Playwright's sync
    client is bound to the thread that started it; Flask may dispatch requests
    to different threads, so all browser work must be serialized here.
    """

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._q: queue.Queue = queue.Queue()
        self._browser_pool: Optional["BrowserPool"] = None
        self._thread = threading.Thread(
            target=self._loop, name="PlaywrightRunner", daemon=True
        )
        self._thread.start()

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                break
            fut, fn = item
            try:
                fut.set_result(fn())
            except BaseException as exc:
                fut.set_exception(exc)

    def run(self, fn, timeout: float = 600.0):
        fut: Future = Future()
        self._q.put((fut, fn))
        return fut.result(timeout=timeout)

    def _ensure_pool(self) -> "BrowserPool":
        """Must run only inside worker thread (via run())."""
        if self._browser_pool is None:
            self._browser_pool = BrowserPool(headless=self._headless)
        return self._browser_pool

    def shutdown(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=60)
        if self._browser_pool is not None:
            self._browser_pool.shutdown()
            self._browser_pool = None


# ---------- Retry defaults (mirrors Java UrlExistenceChecker.Options) ----------
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_INITIAL_DELAY_MS = 400
_DEFAULT_CONNECT_TIMEOUT = 5
_DEFAULT_READ_TIMEOUT = 10

# HTTP status codes that trigger a retry (mirrors Java setRetryStatusCode)
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


class URLValidator:
    """Classe pour valider les URLs"""
    
    @staticmethod
    def is_valid_url(url: str) -> bool:
        """
        Vérifie si une URL est bien formée
        
        Args:
            url: URL à vérifier
            
        Returns:
            True si l'URL est valide
        """
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False
    
    @staticmethod
    def is_malformed_url(url: str) -> bool:
        """
        Vérifie si une URL est mal formée
        
        Args:
            url: URL à vérifier
            
        Returns:
            True si l'URL est mal formée
        """
        return not URLValidator.is_valid_url(url)
    
    @staticmethod
    def get_url_status(url: str, timeout: int = 10,
                       max_retries: int = _DEFAULT_MAX_RETRIES,
                       initial_delay_ms: int = _DEFAULT_INITIAL_DELAY_MS,
                       protected_counts_as_exists: bool = True) -> Tuple[int, Optional[str]]:
        """
        Checks URL accessibility and returns status code and message.
        Tries HEAD first, then falls back to GET (some servers reject HEAD).
        
        Implements retry with exponential backoff on transient errors,
        matching the Java UrlExistenceChecker behaviour.
        
        Args:
            url: URL à vérifier
            timeout: Base timeout in seconds
            max_retries: Maximum number of retry attempts (default 2)
            initial_delay_ms: Initial delay between retries in ms (doubles each retry)
            protected_counts_as_exists: If True, 401/403 are not treated as errors
            
        Returns:
            Tuple of (status_code, error_message)
            - status_code: HTTP status code or None if error
            - error_message: Description of error or None if success
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        def _classify(status: int) -> Tuple[int, Optional[str]]:
            """Translate HTTP status to (code, message) pair."""
            if status < 400:
                return status, None
            elif status == 401:
                return status, "Authentication required"
            elif status == 403:
                return status, "Forbidden / Paywall"
            elif status == 404:
                return status, "Page not found"
            elif 500 <= status < 600:
                # Handle server-side errors explicitly
                return _classify(status)
            else:
                return status, f"HTTP {status}"

        def _is_retryable(status: int) -> bool:
            return status in _RETRYABLE_STATUS_CODES

        # ---------- Attempt HEAD with retries ----------
        head_decided = False
        for attempt in range(max_retries + 1):
            effective_timeout = timeout * (1 + attempt)  # Scale timeout like Java
            try:
                response = requests.head(
                    url, timeout=effective_timeout,
                    allow_redirects=True, headers=headers
                )
                status = response.status_code

                # These codes mean HEAD is rejected/unreliable -> try GET
                # Matches Java: 405, 501, 418, 400, 403, and any 4xx
                if status in (400, 403, 405, 418, 501) or (400 <= status < 500):
                    break

                if _is_retryable(status):
                    raise requests.RequestException(f"Transient HTTP {status}")

                head_decided = True
                return _classify(status)

            except requests.RequestException:
                if attempt < max_retries:
                    delay = (initial_delay_ms * (2 ** attempt)) / 1000.0
                    delay = min(delay, 5.0)
                    time.sleep(delay)
                    continue
                # HEAD exhausted retries - fall through to GET
                break
            except Exception:
                break

        # ---------- Attempt GET with retries ----------
        for attempt in range(max_retries + 1):
            effective_timeout = timeout * (1 + attempt)
            try:
                response = requests.get(
                    url, timeout=effective_timeout,
                    allow_redirects=True, headers=headers, stream=True
                )
                status = response.status_code
                response.close()

                if _is_retryable(status):
                    raise requests.RequestException(f"Transient HTTP {status}")

                return _classify(status)

            except requests.Timeout:
                if attempt >= max_retries:
                    return None, "Timeout"
            except requests.ConnectionError:
                if attempt >= max_retries:
                    return None, "Connection error"
            except requests.RequestException:
                pass
            except Exception as e:
                if attempt >= max_retries:
                    logger.debug(f"URL check failed for {url}: {e}")
                    return None, str(e)

            # Backoff before retry
            if attempt < max_retries:
                delay = (initial_delay_ms * (2 ** attempt)) / 1000.0
                delay = min(delay, 5.0)
                time.sleep(delay)

        return None, "All retries exhausted"
    
    @staticmethod
    def exists_url(url: str, timeout: int = 10,
                   protected_counts_as_exists: bool = True) -> bool:
        """
        Vérifie si une URL existe.
        Matches Java UrlExistenceChecker: 401/403 count as existing by default.
        
        Args:
            url: URL à vérifier
            timeout: Timeout en secondes
            protected_counts_as_exists: If True, 401/403 also count as existing
            
        Returns:
            True si l'URL existe et répond
        """
        status, error = URLValidator.get_url_status(url, timeout)
        if status is None:
            return False
        if status < 400:
            return True
        if protected_counts_as_exists and status in (401, 403):
            return True
        return False
    
    @staticmethod
    def extract_domain(url: str) -> Optional[str]:
        """
        Extrait le domaine d'une URL
        
        Args:
            url: URL
            
        Returns:
            Nom de domaine ou None
        """
        try:
            parsed = urlparse(url)
            return parsed.netloc
        except Exception:
            return None
    
    @staticmethod
    def extract_registrable_domain(url: str) -> Optional[str]:
        """
        Extract the registrable domain from a URL.
        Equivalent to Java's PublicSuffixList.getRegistrableDomain().
        Attempts to use tldextract if available, falls back to simple heuristic.
        
        Examples:
            https://www.ft.com/content/abc  →  ft.com
            https://news.bbc.co.uk/stories  →  bbc.co.uk
        
        Args:
            url: URL
            
        Returns:
            Registrable domain (e.g. "ft.com") or None
        """
        try:
            import tldextract
            ext = tldextract.extract(url)
            if ext.domain and ext.suffix:
                return f"{ext.domain}.{ext.suffix}"
            return None
        except ImportError:
            # Fallback: strip www. prefix from netloc
            try:
                netloc = urlparse(url).netloc
                if netloc.startswith("www."):
                    netloc = netloc[4:]
                return netloc or None
            except Exception:
                return None
    
    @staticmethod
    def is_pdf_url(url: str) -> bool:
        """
        Vérifie si une URL pointe vers un fichier PDF.
        Checks the path extension first, then falls back to a HEAD request
        to inspect the Content-Type header (same logic as Java Utils.isPdfFile).
        
        Args:
            url: URL à vérifier
            
        Returns:
            True si l'URL semble pointer vers un PDF
        """
        # Check file extension in the URL path (ignore query string)
        try:
            path = urlparse(url).path.lower()
            if path.endswith('.pdf'):
                return True
        except Exception:
            pass
        
        # Check Content-Type via HEAD request (equivalent to Java's isPdfFile)
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            content_type = resp.headers.get('Content-Type', '').lower()
            if 'application/pdf' in content_type:
                return True
        except Exception:
            pass
        
        return False


class PDFExtractor:
    """Classe pour extraire du texte depuis des PDFs"""
    
    @staticmethod
    def extract_text_from_pdf(pdf_path: str) -> Optional[str]:
        """
        Extrait le texte d'un fichier PDF
        Utilise PyPDF2 et pdfplumber en fallback
        
        Args:
            pdf_path: Chemin vers le fichier PDF
            
        Returns:
            Texte extrait ou None
        """
        text = None
        
        # Essaie d'abord avec pdfplumber (meilleur pour le texte complexe)
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                text_parts = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                if text_parts:
                    text = "\n".join(text_parts)
                    logger.info(f"Extracted text from PDF using pdfplumber: {len(text)} chars")
        except ImportError:
            logger.debug("pdfplumber not available, trying PyPDF2")
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed: {e}")
        
        # Fallback sur PyPDF2
        if not text:
            try:
                import PyPDF2
                with open(pdf_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    text_parts = []
                    for page in pdf_reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text_parts.append(page_text)
                    if text_parts:
                        text = "\n".join(text_parts)
                        logger.info(f"Extracted text from PDF using PyPDF2: {len(text)} chars")
            except ImportError:
                logger.error("PyPDF2 not available. Install with: pip install PyPDF2")
            except Exception as e:
                logger.error(f"PyPDF2 extraction failed: {e}")
        
        return text
    
    @staticmethod
    def download_pdf(url: str, save_path: Optional[str] = None) -> Optional[str]:
        """
        Télécharge un PDF depuis une URL
        
        Args:
            url: URL du PDF
            save_path: Chemin où sauvegarder (optionnel, utilise temp sinon)
            
        Returns:
            Chemin du fichier téléchargé ou None
        """
        try:
            if save_path is None:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
                save_path = temp_file.name
                temp_file.close()
            
            logger.info(f"Downloading PDF from {url}")
            
            # Télécharge le fichier
            response = requests.get(url, timeout=30, stream=True)
            response.raise_for_status()
            
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"PDF downloaded to {save_path}")
            return save_path
            
        except Exception as e:
            logger.error(f"Failed to download PDF: {e}")
            return None


class BrowserPool:
    """
    Thread-safe pool for reusing Playwright browser instances.
    Mirrors the Java pattern where a single Browser is created in WSContent.load()
    and shared across multiple WebCrawler calls.
    
    Usage::
    
        pool = BrowserPool()
        browser = pool.acquire()       # launches Firefox if needed
        page = browser.new_page()
        # ... use page ...
        page.close()
        pool.release()                 # keeps browser alive for next call
        # When done for the session:
        pool.shutdown()                # closes everything
    """

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._playwright = None  # Playwright context manager result
        self._playwright_cm = None  # The context manager itself
        self._browser = None
        self._in_use = False

    def acquire(self):
        """
        Return a running Playwright Firefox Browser, launching one if needed.
        Blocks if the browser is currently in use by another thread.
        
        Returns:
            playwright.sync_api.Browser instance
        """
        with self._condition:
            # Wait until the browser is not in use
            while self._in_use:
                self._condition.wait(timeout=60)
            if self._browser is None or not self._browser.is_connected():
                self._start_browser()
            self._in_use = True
            return self._browser

    def release(self):
        """Mark the browser as available (does NOT close it)."""
        with self._condition:
            self._in_use = False
            self._condition.notify()

    def shutdown(self):
        """Close the browser and Playwright process."""
        with self._lock:
            self._in_use = False
            try:
                if self._browser and self._browser.is_connected():
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._playwright:
                    self._playwright.stop()
            except Exception:
                pass
            self._browser = None
            self._playwright = None
            self._playwright_cm = None

    def _start_browser(self):
        """Internal: launch Playwright + Firefox."""
        try:
            from playwright.sync_api import sync_playwright
            self._playwright_cm = sync_playwright()
            self._playwright = self._playwright_cm.start()
            self._browser = self._playwright.firefox.launch(headless=self._headless)
            logger.info("BrowserPool: Firefox launched")
        except Exception as e:
            logger.error(f"BrowserPool: failed to launch browser: {e}")
            raise

    def __del__(self):
        self.shutdown()


class WebPageExtractor:
    """
    Classe pour extraire du texte depuis des pages web.
    
    Implements two strategies matching the Java WebCrawler:
    - requests + BeautifulSoup (fast, static pages)
    - Playwright with Firefox Reader Mode + Readability.js fallback (dynamic/JS pages)
    
    Adds authentication support:
    - Per-domain login via Playwright (username/password fill + submit)
    - Cookie-consent handling
    - hCaptcha resolution via CapSolver API
    """
    
    # Readability.js CDN URL - used as fallback when reader mode fails
    READABILITY_JS_CDN = "https://cdn.jsdelivr.net/npm/@piyush-bhatt/readability@0.5.0/Readability.js"
    
    @staticmethod
    def _clean_extracted_text(text: str) -> str:
        """
        Nettoie le texte extrait d'une page web.
        Equivalent to Java's text normalization in fetchText_ReaderMode.
        Enhanced version with better whitespace and duplication handling.
        
        Args:
            text: Texte brut extrait
            
        Returns:
            Texte nettoyé
        """
        if not text:
            return text
        
        # Replace non-breaking spaces
        text = text.replace('\u00A0', ' ')
        # Remove tabs and odd whitespace characters
        text = re.sub(r'[\t\x0B\f\r]', '', text)
        
        # Normalize multiple spaces to single space
        text = re.sub(r'[ ]{2,}', ' ', text)
        
        # Fix newline handling: normalize all line separators
        text = re.sub(r'\n[ \t]+', '\n', text)  # Remove leading spaces after newline
        text = re.sub(r'[ \t]+\n', '\n', text)  # Remove trailing spaces before newline
        
        # Normalize excessive line breaks (3+ newlines → 2)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove "Loading…"
        text = text.replace('Loading…', '').replace('Loading...', '')
        
        # Deduplicate consecutive identical lines
        lines = text.split('\n')
        dedup_lines = []
        prev_line = None
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and line_stripped != prev_line:
                dedup_lines.append(line)
                prev_line = line_stripped
            elif not line_stripped:  # Keep empty lines for paragraph breaks
                dedup_lines.append(line)
        
        text = '\n'.join(dedup_lines)
        
        return text.strip()
    
    # ------------------------------------------------------------------ #
    #  Domain-specific text cleaning (mirrors Java WebCrawler.cleanText)  #
    # ------------------------------------------------------------------ #
    
    @staticmethod
    def _clean_text_for_domain(url: str, text: str, reader_mode: bool = False,
                                media_config: Optional[MediaConfig] = None) -> str:
        """
        Apply domain-specific cleaning rules after extraction.
        Equivalent to Java ``WebCrawler.cleanText()``.
        
        Built-in rules replicate the Java hard-coded logic (ft.com, domain header
        stripping in reader mode).  Additional rules come from ``MediaConfig.cleaning_rules``.
        
        Args:
            url: The source URL (used to determine domain).
            text: Raw extracted text.
            reader_mode: Whether the text came from Firefox Reader Mode.
            media_config: Optional MediaConfig with custom cleaning rules.
            
        Returns:
            Cleaned text.
        """
        if not text:
            return text

        domain = URLValidator.extract_registrable_domain(url) or ""

        # --- Reader-mode: strip everything before the domain name header ---
        if reader_mode and domain and domain in text:
            parts = text.split(domain, 1)
            if len(parts) > 1:
                text = parts[1]
            text = text.replace('Loading…', '').replace('Loading...', '')

        # --- ft.com specific rules (same as Java) ---
        if 'ft.com' in domain:
            if 'Print this page' in text:
                parts = text.split('Print this page', 1)
                if len(parts) > 1:
                    text = parts[1]
            if 'Event details' in text:
                parts = text.split('Event details', 1)
                text = parts[0]

        # --- Custom rules from config (split-before / split-after markers) ---
        if media_config:
            rules = media_config.get_cleaning_rules(domain)
            if rules:
                for rule in rules:
                    marker = rule.get("marker", "")
                    action = rule.get("action", "")  # "remove_before" or "remove_after"
                    if not marker or marker not in text:
                        continue
                    if action == "remove_before":
                        parts = text.split(marker, 1)
                        if len(parts) > 1:
                            text = parts[1]
                    elif action == "remove_after":
                        parts = text.split(marker, 1)
                        text = parts[0]

        return text.strip()

    # ------------------------------------------------------------------ #
    #  Authentication: login + captcha (mirrors Java WebCrawler)          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def login(page, media: Media, capsolver_api_key: str = "") -> Optional[object]:
        """
        Perform login on a page that requires authentication.
        Exact equivalent of Java ``WebCrawler.login()``.
        
        Steps:
          1. Navigate to the media's login URL
          2. Click cookie-consent button if configured
          3. Fill username field, press Enter
          4. Fill password field, press Enter
          5. If captcha is required, solve it via CapSolver API
        
        Args:
            page: Playwright Page object.
            media: Media config for the target domain.
            capsolver_api_key: API key for CapSolver (needed when media.need_captcha).
            
        Returns:
            The same Page object after login, or None if login failed.
        """
        try:
            logger.info(f"Login on: {media.login_url}")
            page.goto(media.login_url, timeout=30000)
            time.sleep(2)

            # Click cookie-consent button if present
            if media.cookie:
                try:
                    loc_button = page.locator(media.cookie)
                    if loc_button.count() > 0:
                        loc_button.click()
                        time.sleep(2)
                except Exception as e:
                    logger.debug(f"Cookie button click failed (non-fatal): {e}")

            # Fill username
            page.fill(media.user_name_field, media.user_name)
            time.sleep(1)
            
            # Some sites require pressing Enter after username to reveal password field
            # But only press on the username field, not the password field
            try:
                page.press(media.user_name_field, "Enter")
                time.sleep(1)
            except Exception:
                pass  # Password field might already be visible

            # Fill password
            page.fill(media.pwd_field, media.pwd)
            time.sleep(1)
            page.press(media.pwd_field, "Enter")
            time.sleep(3)  # Wait for login to complete

            # Always check for captcha (matches Java: always check regardless of needCaptcha)
            loc_captcha = page.locator(
                ".h-captcha, iframe[src*='hcaptcha.com'], textarea[name='h-captcha-response']"
            )
            if loc_captcha.count() > 0:
                if not media.need_captcha:
                    # Unexpected captcha — Java returns null in this case
                    logger.error(f"Unexpected captcha detected on {media.name} but need_captcha=False")
                    return None

                if not capsolver_api_key:
                    logger.error("Captcha detected but no CapSolver API key configured")
                    return None

                captcha_solution = WebPageExtractor._resolve_captcha(
                    capsolver_api_key, media.website_key, media.login_url
                )
                if captcha_solution is None:
                    logger.error("Failed to solve captcha")
                    return None

                g_response = captcha_solution.get("gRecaptchaResponse", "")
                page.evaluate(
                    f"document.getElementsByName('h-captcha-response')[0].value='{g_response}';"
                )
                page.evaluate(
                    "document.getElementsByName('h-captcha-response')[0]"
                    ".dispatchEvent(new Event('change', { bubbles: true }));"
                )
                page.evaluate("document.getElementById('login-form').submit();")
                time.sleep(3)

            logger.info(f"Login completed for {media.name}")
            return page

        except Exception as e:
            logger.error(f"Login failed for {media.name}: {e}")
            return None

    @staticmethod
    def _resolve_captcha(api_key: str, website_key: str, website_url: str) -> Optional[dict]:
        """
        Resolve an hCaptcha challenge using the CapSolver API.
        Exact equivalent of Java ``WebCrawler.resolveCaptcha()``.
        
        Args:
            api_key: CapSolver API key.
            website_key: The hCaptcha site key from the target page.
            website_url: URL of the page with the captcha.
            
        Returns:
            Dict with captcha solution (contains 'gRecaptchaResponse'), or None.
        """
        try:
            payload = {
                "clientKey": api_key,
                "task": {
                    "type": "HCaptchaTaskProxyless",
                    "websiteKey": website_key,
                    "websiteURL": website_url,
                }
            }
            resp = requests.post(
                "https://api.capsolver.com/createTask",
                json=payload,
                timeout=30
            )
            resp.raise_for_status()
            result = resp.json()

            task_id = result.get("taskId")
            if not task_id:
                logger.error(f"CapSolver: no taskId in response: {result}")
                return None

            # Poll for task completion
            for _ in range(60):  # max 60 attempts × 2s = 120s
                time.sleep(2)
                poll_resp = requests.post(
                    "https://api.capsolver.com/getTaskResult",
                    json={"clientKey": api_key, "taskId": task_id},
                    timeout=10,
                )
                poll_result = poll_resp.json()
                status = poll_result.get("status", "")
                if status == "ready":
                    return poll_result.get("solution", {})
                elif status == "failed":
                    logger.error(f"CapSolver task failed: {poll_result}")
                    return None

            logger.error("CapSolver: timeout waiting for solution")
            return None

        except Exception as e:
            logger.error(f"Failed to solve captcha: {e}")
            return None

    # ------------------------------------------------------------------ #
    #  Authenticated Playwright extraction                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _sync_extract_text_with_playwright_authenticated(
        url: str,
        media: Media,
        browser_pool: "BrowserPool",
        capsolver_api_key: str,
        media_config: Optional[MediaConfig],
        timeout: int,
    ) -> Optional[str]:
        """Authenticated fetch using a BrowserPool on the current thread."""
        browser = None
        page = None

        try:
            browser = browser_pool.acquire()
            page = browser.new_page()
            page.set_default_timeout(timeout)

            logged_in_page = page
            if media.need_login:
                logged_in_page = WebPageExtractor.login(page, media, capsolver_api_key)
                if logged_in_page is None:
                    logger.error(
                        f"Authentication failed for {media.name}, attempting without login"
                    )
                    logged_in_page = page

            is_pdf = url.split("?")[0].lower().endswith(".pdf")
            if is_pdf:
                text = WebPageExtractor._download_pdf_authenticated(
                    url, logged_in_page, timeout
                )
                return text

            text = None
            if media.need_text_normal:
                text = WebPageExtractor._fetch_text_normal_mode(url, logged_in_page, timeout)
            else:
                text = WebPageExtractor._fetch_text_reader_mode(url, logged_in_page, timeout)

            if text:
                reader_mode = not media.need_text_normal
                text = WebPageExtractor._clean_text_for_domain(
                    url, text, reader_mode=reader_mode, media_config=media_config
                )
                text = WebPageExtractor._clean_extracted_text(text)

            return text if text and len(text.strip()) > 10 else None

        except Exception as e:
            logger.error(f"Authenticated extraction failed for {url}: {e}")
            return None
        finally:
            try:
                if page:
                    page.close()
            except Exception:
                pass
            browser_pool.release()

    @staticmethod
    def extract_text_with_playwright_authenticated(
        url: str,
        media: Media,
        browser_pool: Optional["BrowserPool"] = None,
        capsolver_api_key: str = "",
        media_config: Optional[MediaConfig] = None,
        timeout: int = 30000,
        runner: Optional["PlaywrightRunner"] = None,
    ) -> Optional[str]:
        """
        Extract text from a page that requires authentication.
        Use ``runner`` under Flask; ``browser_pool`` or ephemeral pool otherwise.
        """
        if runner is not None:

            def _work():
                pool = runner._ensure_pool()
                return WebPageExtractor._sync_extract_text_with_playwright_authenticated(
                    url, media, pool, capsolver_api_key, media_config, timeout
                )

            try:
                return runner.run(_work)
            except Exception as e:
                logger.error(f"Authenticated extraction failed for {url}: {e}")
                return None

        if browser_pool is not None:
            return WebPageExtractor._sync_extract_text_with_playwright_authenticated(
                url, media, browser_pool, capsolver_api_key, media_config, timeout
            )

        pool = BrowserPool()
        try:
            return WebPageExtractor._sync_extract_text_with_playwright_authenticated(
                url, media, pool, capsolver_api_key, media_config, timeout
            )
        finally:
            pool.shutdown()

    @staticmethod
    def _download_pdf_authenticated(url: str, page, timeout: int = 30000) -> Optional[str]:
        """
        Download a PDF via an authenticated Playwright page.
        
        When navigating to a PDF URL after login, the browser triggers a file
        download instead of rendering a page.  Playwright raises
        ``Download is starting`` if we use ``page.goto()`` directly.
        
        This method uses Playwright's download event to capture the file,
        then extracts text from the saved PDF.
        
        Args:
            url: PDF URL (must end in .pdf).
            page: Authenticated Playwright page (already logged in).
            timeout: Timeout in milliseconds.
            
        Returns:
            Extracted text or None.
        """
        import tempfile
        try:
            # Expect a download when navigating to the PDF URL.
            # Use JS navigation (window.location) instead of page.goto() because
            # Playwright's goto() throws "Download is starting" on Firefox
            # when the response triggers a file download.
            with page.expect_download(timeout=timeout) as download_info:
                page.evaluate(f'() => {{ window.location.href = "{url}"; }}')
            
            download = download_info.value
            
            # Save to a temporary file
            temp_path = tempfile.mktemp(suffix='.pdf')
            download.save_as(temp_path)
            logger.info(f"Authenticated PDF downloaded to {temp_path}")
            
            # Extract text from the downloaded PDF
            text = PDFExtractor.extract_text_from_pdf(temp_path)
            
            # Cleanup
            try:
                Path(temp_path).unlink()
            except Exception:
                pass
            
            if text and len(text.strip()) > 10:
                logger.info(f"Extracted {len(text)} chars from authenticated PDF")
                return text
            else:
                logger.warning("No text extracted from authenticated PDF")
                return None
                
        except Exception as e:
            logger.error(f"Authenticated PDF download failed for {url}: {e}")
            return None

    @staticmethod
    def _fetch_text_reader_mode(url: str, page, timeout: int = 30000) -> Optional[str]:
        """
        Extract text using Firefox Reader Mode, with Readability.js fallback.
        Called on an already-open (possibly authenticated) page.
        Equivalent to Java ``fetchText_ReaderMode()``.
        """
        text = None

        # Strategy 1: Firefox about:reader
        try:
            reader_url = f"about:reader?url={url}"
            page.goto(reader_url)
            page.wait_for_selector(
                "#readability-page-1",
                timeout=8000,
                state="attached"
            )
            page.evaluate(
                "const elem = document.getElementById('pocket-cta-container'); if(elem) elem.remove();"
            )
            html_content = page.content()
            text = WebPageExtractor._parse_reader_html(html_content)
            if text and len(text.strip()) > 50:
                return text
        except Exception as e:
            logger.info(f"Reader mode failed, trying Readability.js: {e}")

        # Strategy 2: Inject Readability.js
        try:
            page.goto(url, wait_until='networkidle', timeout=timeout)
            page.add_script_tag(url=WebPageExtractor.READABILITY_JS_CDN)
            page.wait_for_timeout(1000)
            text = page.evaluate("""
                () => {
                    try {
                        let article = new Readability(document.cloneNode(true)).parse();
                        return article ? article.textContent : null;
                    } catch(e) {
                        return null;
                    }
                }
            """)
            if text and len(text.strip()) > 50:
                return text
        except Exception as e:
            logger.info(f"Readability.js injection failed: {e}")

        return text

    @staticmethod
    def _fetch_text_normal_mode(url: str, page, timeout: int = 30000) -> Optional[str]:
        """
        Extract text in normal mode (no reader mode).
        Called on an already-open (possibly authenticated) page.
        Equivalent to Java ``fetchText_NormalMode()``.
        """
        try:
            page.goto(url, wait_until='networkidle', timeout=timeout)
            html_content = page.content()
            text = WebPageExtractor._parse_normal_html(html_content)
            return text
        except Exception as e:
            logger.error(f"Normal mode extraction failed: {e}")
            return None

    @staticmethod
    def extract_text_with_requests(url: str, timeout: int = 30) -> Optional[str]:
        """
        Extrait le texte d'une page web avec requests + BeautifulSoup + readability-lxml.
        Méthode rapide pour les pages statiques.
        Uses readability-lxml for article extraction when available (similar to Java's
        Readability.js), falls back to basic tag-stripping.
        
        Args:
            url: URL de la page
            timeout: Timeout en secondes
            
        Returns:
            Texte extrait ou None
        """
        try:
            from bs4 import BeautifulSoup
            
            # Configure retries
            session = requests.Session()
            retry = Retry(total=3, backoff_factor=0.5)
            adapter = HTTPAdapter(max_retries=retry)
            session.mount('http://', adapter)
            session.mount('https://', adapter)
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            response = session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            
            html = response.text
            
            # Try readability-lxml first (Python equivalent of Readability.js)
            try:
                from readability import Document as ReadabilityDocument
                doc = ReadabilityDocument(html)
                article_html = doc.summary()
                soup = BeautifulSoup(article_html, 'html.parser')
                text = soup.get_text(separator='\n')
                text = WebPageExtractor._clean_extracted_text(text)
                if text and len(text.strip()) > 100:
                    logger.info(f"Extracted text with readability-lxml: {len(text)} chars")
                    return text
            except ImportError:
                logger.debug("readability-lxml not available, using basic extraction")
            except Exception as e:
                logger.debug(f"readability-lxml failed: {e}, falling back to basic extraction")
            
            # Fallback: basic BeautifulSoup extraction
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove scripts, styles, and navigation elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                tag.decompose()
            
            # Try to find article content first
            article = soup.find('article') or soup.find('main') or soup.find(attrs={'role': 'main'})
            if article:
                text = article.get_text(separator='\n')
            else:
                text = soup.get_text(separator='\n')
            
            text = WebPageExtractor._clean_extracted_text(text)
            
            logger.info(f"Extracted text with requests: {len(text)} chars")
            return text
            
        except ImportError:
            logger.error("BeautifulSoup not available. Install with: pip install beautifulsoup4")
            return None
        except Exception as e:
            logger.error(f"Failed to extract text with requests: {e}")
            return None
    
    @staticmethod
    def _sync_extract_text_with_playwright(
        url: str,
        timeout: int,
        browser_pool: "BrowserPool",
        media_config: Optional[MediaConfig],
    ) -> Optional[str]:
        """Same-thread Playwright fetch using a BrowserPool (see PlaywrightRunner)."""
        browser = None
        page = None

        try:
            logger.info(f"Using Playwright to fetch {url}")

            browser = browser_pool.acquire()
            page = browser.new_page()
            page.set_default_timeout(timeout)
                
            text = None

            # Strategy 1: Firefox Reader Mode (equivalent to Java fetchText_ReaderMode)
            try:
                reader_url = f"about:reader?url={url}"
                page.goto(reader_url)
                page.wait_for_selector(
                    "#readability-page-1",
                    timeout=8000,
                    state="attached"
                )
                page.evaluate("const e = document.getElementById('pocket-cta-container'); if(e) e.remove();")
                    
                html_content = page.content()
                text = WebPageExtractor._parse_reader_html(html_content)
                    
                if text and len(text.strip()) > 50:
                    logger.info(f"Extracted text with Firefox Reader Mode: {len(text)} chars")
                    text = WebPageExtractor._clean_text_for_domain(
                        url, text, reader_mode=True, media_config=media_config
                    )
                    text = WebPageExtractor._clean_extracted_text(text)
                    return text
                    
            except Exception as e:
                logger.info(f"Reader mode failed, trying Readability.js: {e}")
                
            # Strategy 2: Navigate normally + inject Readability.js
            try:
                page.goto(url, wait_until='networkidle', timeout=timeout)
                    
                page.add_script_tag(url=WebPageExtractor.READABILITY_JS_CDN)
                page.wait_for_timeout(1000)
                    
                text = page.evaluate("""
                    () => {
                        try {
                            let article = new Readability(document.cloneNode(true)).parse();
                            return article ? article.textContent : null;
                        } catch(e) {
                            return null;
                        }
                    }
                """)
                    
                if text and len(text.strip()) > 50:
                    logger.info(f"Extracted text with Readability.js: {len(text)} chars")
                    text = WebPageExtractor._clean_text_for_domain(
                        url, text, reader_mode=False, media_config=media_config
                    )
                    text = WebPageExtractor._clean_extracted_text(text)
                    return text
                    
            except Exception as e:
                logger.info(f"Readability.js failed: {e}, trying basic extraction")
                
            # Strategy 3: Basic text extraction (equivalent to Java fetchText_NormalMode)
            try:
                if 'about:reader' in page.url:
                    page.goto(url, wait_until='networkidle', timeout=timeout)
                    
                html_content = page.content()
                text = WebPageExtractor._parse_normal_html(html_content)
                    
                if text and len(text.strip()) > 50:
                    logger.info(f"Extracted text with basic Playwright extraction: {len(text)} chars")
                    text = WebPageExtractor._clean_text_for_domain(
                        url, text, reader_mode=False, media_config=media_config
                    )
                    text = WebPageExtractor._clean_extracted_text(text)
                    return text
                        
            except Exception as e:
                logger.warning(f"Basic extraction also failed: {e}")
            
            return WebPageExtractor._clean_extracted_text(text) if text else None
            
        except ImportError:
            logger.error("Playwright not available. Install with: pip install playwright && playwright install")
            return None
        except Exception as e:
            logger.error(f"Failed to extract text with Playwright: {e}")
            return None
        finally:
            try:
                if page:
                    page.close()
            except Exception:
                pass
            browser_pool.release()
    
    @staticmethod
    def extract_text_with_playwright(
        url: str,
        timeout: int = 30000,
        browser_pool: Optional["BrowserPool"] = None,
        media_config: Optional[MediaConfig] = None,
        runner: Optional["PlaywrightRunner"] = None,
    ) -> Optional[str]:
        """
        Extrait le texte d'une page web avec Playwright.
        Prefers ``runner`` (dedicated thread) for Flask; ``browser_pool`` for
        same-thread use; otherwise creates a short-lived pool on this thread.
        """
        if runner is not None:

            def _work():
                pool = runner._ensure_pool()
                return WebPageExtractor._sync_extract_text_with_playwright(
                    url, timeout, pool, media_config
                )

            try:
                return runner.run(_work)
            except Exception as e:
                logger.error(f"Failed to extract text with Playwright: {e}")
                return None

        if browser_pool is not None:
            try:
                return WebPageExtractor._sync_extract_text_with_playwright(
                    url, timeout, browser_pool, media_config
                )
            except Exception as e:
                logger.error(f"Failed to extract text with Playwright: {e}")
                return None

        pool = BrowserPool()
        try:
            return WebPageExtractor._sync_extract_text_with_playwright(
                url, timeout, pool, media_config
            )
        except Exception as e:
            logger.error(f"Failed to extract text with Playwright: {e}")
            return None
        finally:
            pool.shutdown()
    
    @staticmethod
    def _parse_reader_html(html_content: str) -> Optional[str]:
        """
        Parse HTML from Firefox Reader Mode output.
        Equivalent to Java's Jsoup parsing in fetchText_ReaderMode.
        
        Args:
            html_content: HTML content from reader mode
            
        Returns:
            Extracted text or None
        """
        try:
            from bs4 import BeautifulSoup
            
            # Convert block-level tags to newlines (same as Java)
            html_content = re.sub(r'(?i)<br[^>]*>', '\n', html_content)
            html_content = re.sub(r'(?i)</p>', '\n\n', html_content)
            html_content = re.sub(r'(?i)</div>', '\n', html_content)
            html_content = re.sub(r'(?i)<div[^>]*>', '\n', html_content)
            html_content = html_content.replace('&nbsp;', ' ')
            
            soup = BeautifulSoup(html_content, 'html.parser')
            text = soup.get_text()
            
            return text
        except Exception as e:
            logger.error(f"Failed to parse reader HTML: {e}")
            return None
    
    @staticmethod
    def _parse_normal_html(html_content: str) -> Optional[str]:
        """
        Parse HTML in normal mode: extract text from all <div> elements
        with deduplication, matching Java's fetchText_NormalMode algorithm.
        Falls back to semantic detection if no divs found.
        
        Args:
            html_content: Raw HTML content
            
        Returns:
            Extracted text or None
        """
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove scripts, styles, and non-content elements
            for tag in soup(["script", "style", "noscript", "meta", "link"]):
                tag.decompose()
            
            # Java algorithm: iterate all <div> elements, extract text,
            # deduplicate by checking if text is already in the accumulated output
            divs = soup.find_all('div')
            if divs:
                collected_text = []
                seen_text = set()
                for div in divs:
                    div_text = div.get_text(strip=True)
                    if div_text and div_text not in seen_text:
                        collected_text.append(div_text)
                        seen_text.add(div_text)
                if collected_text:
                    text = '\n'.join(collected_text)
                    return text
            
            # Fallback: semantic content detection
            content = (
                soup.find('article') or
                soup.find('main') or
                soup.find(attrs={'role': 'main'})
            )
            if not content:
                content = soup.find('body')
                if content:
                    for tag in content(['nav', 'footer', 'header', 'aside', 'noscript']):
                        tag.decompose()
            
            if content:
                text = content.get_text(separator='\n', strip=True)
            else:
                text = soup.get_text(separator='\n', strip=True)
            
            return text if text else None
            
        except Exception as e:
            logger.error(f"Failed to parse normal HTML: {e}")
            return None


class WebScraper:
    """
    Classe principale pour le web scraping.
    Équivalent du load() Java (WSContent + WebCrawler) avec améliorations.
    
    Integrates:
    - MediaConfig for per-domain auth and exclusion rules
    - BrowserPool for persistent Playwright browser reuse
    - Authenticated extraction (login + captcha) for protected pages
    - Domain-specific text cleaning
    """
    
    def __init__(self, 
                 use_playwright: bool = True,
                 timeout: int = 30,
                 excluded_domains: Optional[list] = None,
                 media_config: Optional[MediaConfig] = None,
                 browser_pool: Optional[BrowserPool] = None,
                 config_path: Optional[str] = None):
        """
        Initialise le web scraper.
        
        Args:
            use_playwright: Si True, utilise Playwright par défaut (gère le JS, recommandé)
            timeout: Timeout en secondes
            excluded_domains: Liste de domaines à exclure (merged with media_config.exclusions)
            media_config: MediaConfig instance. If None, loaded from config.json automatically.
            browser_pool: Optional shared BrowserPool (same-thread only). If None, a
                PlaywrightRunner is used so Playwright stays on one thread (Flask-safe).
            config_path: Path to config.json (only used if media_config is None).
        """
        self.use_playwright = use_playwright
        self.timeout = timeout
        self.validator = URLValidator()
        self.pdf_extractor = PDFExtractor()
        self.web_extractor = WebPageExtractor()
        
        # Load media config
        if media_config is not None:
            self.media_config = media_config
        else:
            self.media_config = MediaConfig.from_config_file(config_path)
        
        # Merge explicit excluded_domains with config exclusions
        self.excluded_domains = set(excluded_domains or [])
        self.excluded_domains.update(self.media_config.exclusions)
        
        self._browser_pool = browser_pool
        self._owns_pool = browser_pool is None
        self._pw_runner: Optional[PlaywrightRunner] = None

    def _playwright_targets(self) -> Tuple[Optional[BrowserPool], Optional[PlaywrightRunner]]:
        """Return (browser_pool, runner) for Playwright extractors — never both set."""
        if self._browser_pool is not None:
            return self._browser_pool, None
        if self._pw_runner is None:
            self._pw_runner = PlaywrightRunner()
        return None, self._pw_runner
    
    def shutdown(self):
        """
        Release PlaywrightRunner or an owned BrowserPool.
        Call this when done processing a batch of URLs.
        """
        if self._pw_runner is not None:
            self._pw_runner.shutdown()
            self._pw_runner = None
        if self._owns_pool and self._browser_pool is not None:
            self._browser_pool.shutdown()
            self._browser_pool = None
    
    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass
    
    def is_excluded_domain(self, url: str) -> bool:
        """
        Vérifie si le domaine de l'URL est exclu.
        Checks both explicit exclusions and MediaConfig exclusions.
        """
        # Check registrable domain first (matches Java behaviour)
        reg_domain = self.validator.extract_registrable_domain(url)
        if reg_domain and reg_domain in self.excluded_domains:
            return True
        if reg_domain and self.media_config.is_excluded(reg_domain):
            return True
        
        # Fallback: check full netloc with exact matching (not substring)
        domain = self.validator.extract_domain(url)
        if not domain:
            return False
        domain_lower = domain.lower()
        return any(
            domain_lower == excl or domain_lower.endswith('.' + excl)
            for excl in self.excluded_domains
        )
    
    def _identify_specific_media(self, url: str) -> Optional[Media]:
        """
        Identify whether a URL requires specific processing (login, special mode).
        Equivalent to Java ``WebCrawler.identifySpecificUrl()``.
        
        Args:
            url: Target URL.
            
        Returns:
            Media config if domain has specific handling, else None.
        """
        domain = self.validator.extract_registrable_domain(url)
        if domain and self.media_config.is_specific(domain):
            return self.media_config.get_specific(domain)
        return None
    
    def load(self, url: str, force_playwright: bool = False) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Charge et extrait le contenu d'une URL.
        Équivalent Python du load() Java (WSContent.load + WebCrawler.fetchText).
        
        Flow (mirrors Java):
          1. Validate URL
          2. Check exclusions
          3. Check URL accessibility (with retries)
          4. If PDF -> download + extract
          5. If specific media -> authenticated Playwright extraction
          6. Else -> requests fast path, then Playwright fallback
        
        Args:
            url: URL à charger
            force_playwright: Force l'utilisation de Playwright même si use_playwright=False
            
        Returns:
            Tuple (texte_extrait, metadata)
            metadata contient: {
                'success': bool,
                'error': Optional[str],
                'url': str,
                'is_pdf': bool,
                'method': str,  # 'requests', 'playwright', 'playwright_auth', 'pdf'
                'text_length': int,
                'media': Optional[str],  # media name if specific handling was used
                'auth_attempted': bool
            }
        """
        metadata = {
            'success': False,
            'error': None,
            'url': url,
            'is_pdf': False,
            'method': None,
            'text_length': 0,
            'media': None,
            'auth_attempted': False,
        }
        
        # Validation de l'URL
        if self.validator.is_malformed_url(url):
            metadata['error'] = "URL_MALFORMED"
            logger.error(f"Malformed URL: {url}")
            return None, metadata
        
        # Vérifie si le domaine est exclu
        if self.is_excluded_domain(url):
            metadata['error'] = "DOMAIN_EXCLUDED"
            logger.warning(f"Domain excluded: {url}")
            return None, metadata
        
        # Vérifie si l'URL existe (with retries + exponential backoff)
        status_code, error_msg = self.validator.get_url_status(url, timeout=self.timeout)
        
        # Only block on truly unreachable URLs (no TCP connection at all).
        # Java WebCrawler.fetchText() does NOT check status — it always attempts
        # extraction via Playwright, which can render pages returning 404/5xx.
        # We log warnings but continue to extraction.
        if status_code is None:
            # Could not connect at all — network error or DNS failure
            logger.warning(f"URL not accessible: {url} - {error_msg}")
            logger.info("Attempting Playwright extraction despite connectivity issues...")
        elif status_code == 404:
            logger.warning(f"Page not found (404): {url} — will still attempt extraction")
        elif status_code >= 500:
            logger.warning(f"Server error ({status_code}): {url} — will still attempt extraction")
        elif status_code in (401, 403):
            logger.warning(f"URL requires authentication/has paywall ({status_code}): {url}")
            logger.info("Attempting extraction despite authentication requirement...")
        
        # Check for domain-specific handling (login, special extraction mode)
        # IMPORTANT: check media BEFORE PDF routing so that authenticated PDFs
        # go through the Playwright-authenticated path (which can handle downloads).
        media = self._identify_specific_media(url)
        if media:
            metadata['media'] = media.name
            if self.validator.is_pdf_url(url):
                metadata['is_pdf'] = True
            return self._load_webpage_authenticated(url, metadata, media)
        
        # Traite les PDFs (unauthenticated)
        if self.validator.is_pdf_url(url):
            return self._load_pdf(url, metadata)
        
        # Standard extraction
        return self._load_webpage(url, metadata, force_playwright)
    
    def _load_pdf(self, url: str, metadata: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Charge et extrait le texte d'un PDF.
        """
        metadata['is_pdf'] = True
        metadata['method'] = 'pdf'
        
        pdf_path = self.pdf_extractor.download_pdf(url)
        
        if not pdf_path:
            metadata['error'] = "PDF_DOWNLOAD_FAILED"
            return None, metadata
        
        try:
            text = self.pdf_extractor.extract_text_from_pdf(pdf_path)
            
            if text and len(text.strip()) > 0:
                metadata['success'] = True
                metadata['text_length'] = len(text)
                logger.info(f"Successfully extracted {len(text)} chars from PDF")
                return text, metadata
            else:
                metadata['error'] = "PDF_NO_TEXT"
                return None, metadata
                
        finally:
            try:
                Path(pdf_path).unlink()
            except Exception:
                pass
    
    def _load_webpage_authenticated(
        self, url: str, metadata: Dict[str, Any], media: Media
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Load a webpage using authenticated Playwright extraction.
        Equivalent to Java flow: identifySpecificUrl -> login -> fetchText.
        
        Args:
            url: Target URL.
            metadata: Metadata dict to populate.
            media: Media config for this domain.
            
        Returns:
            Tuple (text, metadata).
        """
        metadata['auth_attempted'] = media.need_login
        
        pool, pw_runner = self._playwright_targets()
        text = self.web_extractor.extract_text_with_playwright_authenticated(
            url=url,
            media=media,
            browser_pool=pool,
            capsolver_api_key=self.media_config.capsolver_api_key,
            media_config=self.media_config,
            timeout=self.timeout * 1000,
            runner=pw_runner,
        )
        
        if text and len(text.strip()) > 0:
            metadata['success'] = True
            metadata['method'] = 'playwright_auth'
            metadata['text_length'] = len(text)
            logger.info(f"Successfully extracted {len(text)} chars (authenticated) from {media.name}")
            return text, metadata
        
        # Fallback: try standard extraction (without auth)
        logger.warning(f"Authenticated extraction failed for {media.name}, trying standard extraction")
        return self._load_webpage(url, metadata, force_playwright=True)
    
    def _load_webpage(self, 
                     url: str, 
                     metadata: Dict[str, Any],
                     force_playwright: bool = False) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Charge et extrait le texte d'une page web (standard, non-authenticated).
        """
        text = None
        
        # Essaie d'abord avec requests si Playwright n'est pas forcé
        if not self.use_playwright and not force_playwright:
            text = self.web_extractor.extract_text_with_requests(url, self.timeout)
            if text:
                metadata['method'] = 'requests'
        
        # Fallback sur Playwright si requests a échoué ou si forcé
        if not text:
            pool, pw_runner = self._playwright_targets()
            text = self.web_extractor.extract_text_with_playwright(
                url,
                timeout=self.timeout * 1000,
                browser_pool=pool,
                media_config=self.media_config,
                runner=pw_runner,
            )
            if text:
                metadata['method'] = 'playwright'
        
        # Vérifie le résultat
        if text and len(text.strip()) > 0:
            metadata['success'] = True
            metadata['text_length'] = len(text)
            logger.info(f"Successfully extracted {len(text)} chars from webpage")
            return text, metadata
        else:
            metadata['error'] = "TEXT_EXTRACTION_FAILED"
            return None, metadata


# Fonction utilitaire pour usage simple
def load_url(url: str, 
             use_playwright: bool = True,
             timeout: int = 30,
             excluded_domains: Optional[list] = None,
             media_config: Optional[MediaConfig] = None,
             config_path: Optional[str] = None) -> Optional[str]:
    """
    Fonction utilitaire pour charger une URL simplement.
    
    Args:
        url: URL à charger
        use_playwright: Utiliser Playwright (gère le JS, recommandé pour la plupart des sites)
        timeout: Timeout en secondes
        excluded_domains: Domaines à exclure
        media_config: Optional MediaConfig (loaded from config.json if None)
        config_path: Path to config.json
        
    Returns:
        Texte extrait ou None
    """
    scraper = WebScraper(
        use_playwright=use_playwright,
        timeout=timeout,
        excluded_domains=excluded_domains,
        media_config=media_config,
        config_path=config_path,
    )
    try:
        text, metadata = scraper.load(url)
        
        if metadata['success']:
            return text
        else:
            logger.error(f"Failed to load {url}: {metadata['error']}")
            return None
    finally:
        scraper.shutdown()
