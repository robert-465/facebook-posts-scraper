import hashlib
import logging
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from .utils_time import now_timestamp

logger = logging.getLogger(__name__)

@dataclass
class AuthorInfo:
    id: Optional[str]
    name: Optional[str]
    url: Optional[str]

@dataclass
class MediaInfo:
    url: Optional[str]

@dataclass
class PostRecord:
    post_id: Optional[str]
    url: str
    message: Optional[str]
    timestamp: int
    comments_count: int
    reactions_count: int
    author: AuthorInfo
    image: MediaInfo
    video: MediaInfo
    attached_post_url: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Ensure nested dataclasses are converted to dicts
        data["author"] = asdict(self.author)
        data["image"] = asdict(self.image)
        data["video"] = asdict(self.video)
        return data

class FacebookPostsScraper:
    """
    Lightweight scraper that fetches public Facebook pages or posts
    and extracts basic metadata using OpenGraph tags and simple heuristics.

    This implementation intentionally avoids relying on fragile,
    obfuscated selectors and does not attempt to bypass any access controls.
    """

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        user_agent: Optional[str] = None,
        proxies: Optional[Dict[str, str]] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent or self.DEFAULT_USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        if proxies:
            self.session.proxies.update(proxies)
        logger.debug(
            "FacebookPostsScraper initialized (timeout=%s, max_retries=%s)",
            timeout,
            max_retries,
        )

    # ---------- Public API ----------

    def fetch_and_parse(self, url: str) -> List[Dict[str, Any]]:
        html = self._fetch_html_with_retries(url)
        if not html:
            return []
        posts = self._parse_single_post_page(url, html)
        return [post.to_dict() for post in posts]

    # ---------- HTTP + Retry ----------

    def _fetch_html_with_retries(self, url: str) -> Optional[str]:
        delay = self.backoff_factor
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info("Fetching URL (attempt %d/%d): %s", attempt, self.max_retries, url)
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code >= 500:
                    logger.warning(
                        "Received server error %s from %s", response.status_code, url
                    )
                else:
                    response.raise_for_status()
                    return response.text
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Request error while fetching %s (attempt %d/%d): %s",
                    url,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2

        logger.error("Failed to fetch %s after %d attempts: %s", url, self.max_retries, last_error)
        return None

    # ---------- Parsing Logic ----------

    def _parse_single_post_page(self, url: str, html: str) -> List[PostRecord]:
        soup = BeautifulSoup(html, "html.parser")

        og_title = self._get_meta_property(soup, "og:title")
        og_description = self._get_meta_property(soup, "og:description")
        og_site_name = self._get_meta_property(soup, "og:site_name")
        og_url = self._get_meta_property(soup, "og:url") or url
        og_image = self._get_meta_property(soup, "og:image")
        og_video = self._get_meta_property(soup, "og:video")

        message = og_description or og_title or self._extract_text_fallback(soup)
        author_name = og_site_name
        author_url = self._extract_author_url(soup) or self._infer_author_url_from_post_url(og_url)
        author_id = self._derive_author_id(author_url)

        post_id = self._extract_post_id_from_url(og_url) or self._hash_url(og_url)

        timestamp = now_timestamp()
        comments_count = self._extract_int_from_html(soup, ["comments", "comment"])
        reactions_count = self._extract_int_from_html(soup, ["likes", "reactions", "reacted"])

        record = PostRecord(
            post_id=post_id,
            url=og_url,
            message=message,
            timestamp=timestamp,
            comments_count=comments_count,
            reactions_count=reactions_count,
            author=AuthorInfo(id=author_id, name=author_name, url=author_url),
            image=MediaInfo(url=og_image),
            video=MediaInfo(url=og_video),
            attached_post_url=self._extract_attached_post_url(soup),
        )

        return [record]

    # ---------- Helper Methods ----------

    @staticmethod
    def _get_meta_property(soup: BeautifulSoup, prop: str) -> Optional[str]:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find(
            "meta", attrs={"name": prop}
        )
        if tag and tag.get("content"):
            return tag["content"].strip()
        return None

    @staticmethod
    def _extract_text_fallback(soup: BeautifulSoup) -> Optional[str]:
        # Fallback to the page title if nothing else is usable
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        return None

    @staticmethod
    def _extract_author_url(soup: BeautifulSoup) -> Optional[str]:
        # Simple heuristic: look for profile links in header/avatar anchors
        possible = soup.select("a[href*='facebook.com']")
        for a in possible:
            href = a.get("href")
            if not href:
                continue
            if "profile.php" in href or "/pages/" in href:
                return href
        return None

    @staticmethod
    def _infer_author_url_from_post_url(post_url: str) -> Optional[str]:
        """
        Infer a profile/page URL from a post URL if possible,
        e.g. https://www.facebook.com/somepage/posts/123 -> /somepage
        """
        try:
            parsed = urlparse(post_url)
        except Exception:  # noqa: BLE001
            return None

        path_parts = [p for p in parsed.path.split("/") if p]
        if not path_parts:
            return None

        # For URLs like /username/posts/ID -> take first segment as profile/page
        return f"{parsed.scheme}://{parsed.netloc}/{path_parts[0]}"

    @staticmethod
    def _derive_author_id(author_url: Optional[str]) -> Optional[str]:
        if not author_url:
            return None
        try:
            parsed = urlparse(author_url)
            qs = parse_qs(parsed.query)
            if "id" in qs and qs["id"]:
                return qs["id"][0]
        except Exception:  # noqa: BLE001
            return None
        # Fallback: hashed URL
        return hashlib.sha256(author_url.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _extract_post_id_from_url(post_url: str) -> Optional[str]:
        try:
            parsed = urlparse(post_url)
            qs = parse_qs(parsed.query)

            # Common pattern: story_fbid or fbid parameter
            for key in ("story_fbid", "fbid"):
                if key in qs and qs[key]:
                    return qs[key][0]

            # For paths that contain the ID as a segment
            path_parts = [p for p in parsed.path.split("/") if p]
            for part in reversed(path_parts):
                if part.isdigit():
                    return part
        except Exception:  # noqa: BLE001
            return None
        return None

    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _extract_int_from_html(soup: BeautifulSoup, keywords: List[str]) -> int:
        """
        Very lightweight heuristic to find integers near keywords like 'comments' or 'likes'.
        """
        text = soup.get_text(" ", strip=True).lower()
        best_value = 0
        for kw in keywords:
            idx = text.find(kw.lower())
            if idx == -1:
                continue
            window = text[max(0, idx - 20) : idx + 20]
            tokens = window.split()
            for token in tokens:
                token_clean = token.replace(",", "")
                if token_clean.isdigit():
                    try:
                        value = int(token_clean)
                    except ValueError:
                        continue
                    if value > best_value:
                        best_value = value
        return best_value

    @staticmethod
    def _extract_attached_post_url(soup: BeautifulSoup) -> Optional[str]:
        """
        Attempt to find links that look like shared posts.
        This is intentionally simple and conservative.
        """
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "facebook.com" in href and ("story_fbid=" in href or "/posts/" in href):
                return href
        return None