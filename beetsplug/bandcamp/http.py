from functools import lru_cache
from html import unescape
from urllib.parse import urlsplit

from beets import __version__
import httpx

HTTPError = httpx.HTTPError

USER_AGENT = f"beets/{__version__} +https://beets.io/"

_client = httpx.Client(headers={"User-Agent": USER_AGENT})

@lru_cache(maxsize=None)
def http_get_text(url: str) -> str:
    """Return text contents of the url."""

    response = _client.get(url)
    response.raise_for_status()

    return unescape(response.text)
