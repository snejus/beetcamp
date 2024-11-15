from functools import cache
from html import unescape

import httpx
from beets import __version__

HTTPError = httpx.HTTPError

USER_AGENT = f"beets/{__version__} +https://beets.io/"

_client = httpx.Client(headers={"User-Agent": USER_AGENT})


@cache
def http_get_text(url: str) -> str:
    """Return text contents of the url."""

    response = _client.get(url, follow_redirects=True)
    response.raise_for_status()

    return unescape(response.text)
