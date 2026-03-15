import html
import logging
import re
import time
from typing import Optional, Tuple
from urllib.parse import urljoin

import requests


LOGGER = logging.getLogger(__name__)


class VehicleImageResolver:
    CDN_IMAGE_URL = "https://static.encyclopedia.warthunder.com/images/{slug}.png"
    WIKI_UNIT_URL = "https://wiki.warthunder.com/unit/{slug}"

    _GAME_ID_PATTERN = re.compile(r'"gameId"\s*:\s*"([^"]+)"')
    _IMAGE_PATTERN = re.compile(r'<img class="game-unit_template-image" src="([^"]+)"')
    _OG_IMAGE_PATTERN = re.compile(r'<meta name="og:image" content="([^"]+)"')

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout: int = 2,
        retry_cooldown: int = 300,
        logger: Optional[logging.Logger] = None,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retry_cooldown = retry_cooldown
        self.logger = logger or LOGGER
        self._cache = {}

    @staticmethod
    def extract_vehicle_slug(raw_vehicle_type: Optional[str]) -> str:
        if not raw_vehicle_type:
            return "Unknown"

        slug = str(raw_vehicle_type).strip().split("/")[-1]
        return slug or "Unknown"

    @staticmethod
    def format_vehicle_name(vehicle_slug: Optional[str]) -> str:
        if not vehicle_slug:
            return "Unknown"
        return vehicle_slug.replace("_", " ")

    def resolve(self, vehicle_slug: Optional[str]) -> Tuple[Optional[str], str]:
        if not vehicle_slug or vehicle_slug == "Unknown":
            return None, "missing_slug"

        now = time.time()
        cached_entry = self._cache.get(vehicle_slug)
        if cached_entry:
            if cached_entry["url"]:
                return cached_entry["url"], cached_entry["status"]
            if now < cached_entry["next_retry_at"]:
                return None, cached_entry["status"]

        image_url, status, canonical_slug = self._resolve_live(vehicle_slug)
        cache_entry = {
            "url": image_url,
            "status": status,
            "canonical_slug": canonical_slug or vehicle_slug,
            "next_retry_at": 0 if image_url else now + self.retry_cooldown,
        }

        self._cache[vehicle_slug] = cache_entry
        if canonical_slug and canonical_slug != vehicle_slug:
            self._cache[canonical_slug] = cache_entry

        return image_url, status

    def _resolve_live(self, vehicle_slug: str) -> Tuple[Optional[str], str, Optional[str]]:
        direct_image_url = self.CDN_IMAGE_URL.format(slug=vehicle_slug)
        if self._is_valid_image_url(direct_image_url):
            return direct_image_url, "resolved_direct", vehicle_slug

        wiki_html = self._fetch_wiki_page(vehicle_slug)
        if not wiki_html:
            return None, "fallback_no_wiki", None

        page_image_url = self._extract_image_url(wiki_html, vehicle_slug)
        if page_image_url and self._is_valid_image_url(page_image_url):
            return page_image_url, "resolved_from_wiki", self._extract_game_id(wiki_html) or vehicle_slug

        canonical_slug = self._extract_game_id(wiki_html)
        if canonical_slug:
            canonical_image_url = self.CDN_IMAGE_URL.format(slug=canonical_slug)
            if self._is_valid_image_url(canonical_image_url):
                return canonical_image_url, "resolved_canonical", canonical_slug

        return None, "fallback_not_found", canonical_slug

    def _fetch_wiki_page(self, vehicle_slug: str) -> Optional[str]:
        wiki_url = self.WIKI_UNIT_URL.format(slug=vehicle_slug)
        try:
            response = self.session.get(wiki_url, timeout=self.timeout)
            if response.ok:
                return response.text
        except requests.RequestException as exc:
            self.logger.debug("Failed to fetch wiki page for %s: %s", vehicle_slug, exc)
        return None

    def _is_valid_image_url(self, image_url: str) -> bool:
        try:
            response = self.session.get(image_url, timeout=self.timeout, stream=True)
            try:
                return response.ok and response.headers.get("content-type", "").startswith("image/")
            finally:
                response.close()
        except requests.RequestException as exc:
            self.logger.debug("Failed to verify image URL %s: %s", image_url, exc)
            return False

    def _extract_game_id(self, wiki_html: str) -> Optional[str]:
        match = self._GAME_ID_PATTERN.search(wiki_html)
        return match.group(1) if match else None

    def _extract_image_url(self, wiki_html: str, vehicle_slug: str) -> Optional[str]:
        for pattern in (self._IMAGE_PATTERN, self._OG_IMAGE_PATTERN):
            match = pattern.search(wiki_html)
            if match:
                image_url = html.unescape(match.group(1))
                return urljoin(self.WIKI_UNIT_URL.format(slug=vehicle_slug), image_url)
        return None
