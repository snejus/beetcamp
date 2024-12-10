import atexit
import re
from functools import cache, partial
from html import unescape

import beets
import httpx

HTTPError = httpx.HTTPError

USER_AGENT = f"beets/{beets.__version__} +https://beets.io/"

_client = httpx.Client(headers={"User-Agent": USER_AGENT})

_rm_single_quote_dot = partial(re.compile(r"'|(?<=\d)\.(?=\d)").sub, "")
_non_ascii_to_dash = partial(re.compile(r"\W", flags=re.ASCII).sub, "-")
_squeeze_dashes = partial(re.compile(r"--+").sub, "-")


@atexit.register
def close_client() -> None:
    """Close the http client at exit."""
    _client.close()


@cache
def http_get_text(url: str) -> str:
    """Return text contents of the url."""

    response = _client.get(url, follow_redirects=True)
    response.raise_for_status()

    return unescape(response.text)


def urlify(pretty_string: str) -> str:
    """Transform a string into bandcamp url."""
    name = _rm_single_quote_dot(pretty_string.lower())
    return _squeeze_dashes(_non_ascii_to_dash(name)).strip("-")
