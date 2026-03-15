from __future__ import annotations

import json
import logging
import webbrowser
from argparse import Action, ArgumentParser
from functools import partial
from typing import TYPE_CHECKING, Any

import httpx
from beets import config

from .helpers import cached_patternprop
from .http import http_get_text
from .metaguru import Metaguru
from .search import search_bandcamp

if TYPE_CHECKING:
    from argparse import Namespace

    from beets import IncludeLazyConfig
    from beets.autotag.hooks import AlbumInfo, TrackInfo

DEFAULT_CONFIG = {
    "include_digital_only_tracks": True,
    "search_max": 2,
    "art": False,
    "exclude_extra_fields": [],
    "genre": {
        "capitalize": False,
        "maximum": 0,
        "mode": "progressive",
        "always_include": [],
    },
    "comments_separator": "\n---\n",
    "truncate_comments": False,
}


class GuruMixin:
    ALBUM_SLUG_IN_TRACK = cached_patternprop(r'(?<=<a id="buyAlbumLink" href=")[^"]+')

    _log: logging.Logger
    config: IncludeLazyConfig

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not hasattr(self, "_log"):
            self._log = logging.getLogger(__name__)
        if not hasattr(self, "config"):
            self.config = config["beetcamp"]
        self.config.add(DEFAULT_CONFIG)

    def _exc(self, msg_template: str, *args: object) -> None:
        self._log.log(logging.WARNING, msg_template, *args, exc_info=True)

    def _info(self, msg_template: str, *args: object) -> None:
        self._log.log(logging.DEBUG, msg_template, *args, exc_info=False)

    def _get(self, url: str) -> str:
        """Return text contents of the url response."""
        try:
            return http_get_text(url)
        except httpx.HTTPError as e:
            self._info(f"HTTP error obtaining {url}: {e}")
            return ""

    def guru(self, url: str) -> Metaguru | None:
        try:
            return Metaguru.from_html(self._get(url), config=self.config.flatten())
        except (KeyError, ValueError, AttributeError, IndexError) as e:
            self._info("Failed obtaining {}: {}", url, e)
        except Exception:
            i_url = "https://github.com/snejus/beetcamp/issues/new"
            self._exc("Unexpected error obtaining {}, please report at {}", url, i_url)

        return None

    def get_album_info(self, url: str) -> list[AlbumInfo] | None:
        """Return an AlbumInfo object for a bandcamp album page.

        If track url is given by mistake, find and fetch the album url instead.
        """
        html = self._get(url)
        if html and "/track/" in url and (m := self.ALBUM_SLUG_IN_TRACK.search(html)):
            label_url = url.split(r"/track/")[0]
            url = f"{label_url}{m[0]}"

        return guru.albums if (guru := self.guru(url)) else None

    def get_track_info(self, url: str) -> TrackInfo | None:
        """Return a TrackInfo object for a bandcamp track page."""
        return guru.singleton if (guru := self.guru(url)) else None


def get_args() -> Namespace:
    parser = ArgumentParser(
        description="""Get bandcamp release metadata from the given <release-url>
or perform bandcamp search with <query>. Anything that does not start with https://
will be assumed to be a query.

Search type flags: -a for albums, -l for labels and artists, -t for tracks.
By default, all types are searched.
"""
    )

    class UrlOrQueryAction(Action):
        def __call__(
            self,
            parser: ArgumentParser,  # noqa: ARG002
            namespace: Namespace,
            values: Any,
            option_string: str | None = None,  # noqa: ARG002
        ) -> None:
            if values:
                if values.startswith("https://"):
                    target = "release_url"
                else:
                    target = "query"
                    del namespace.release_url
                setattr(namespace, target, values)

    exclusive = parser.add_mutually_exclusive_group(required=True)
    exclusive.add_argument(
        "release_url",
        action=UrlOrQueryAction,
        nargs="?",
        help="Release URL, starting with https:// OR",
    )
    exclusive.add_argument(
        "query", action=UrlOrQueryAction, default="", nargs="?", help="Search query"
    )

    store_const = partial(
        parser.add_argument, dest="search_type", action="store_const", default=""
    )
    store_const("-a", "--album", const="a", help="Search albums")
    store_const("-l", "--label", const="b", help="Search labels and artists")
    store_const("-t", "--track", const="t", help="Search tracks")
    parser.add_argument(
        "-o",
        "--open",
        action="store",
        dest="index",
        type=int,
        help="Open search result indexed by INDEX in the browser",
    )
    parser.add_argument(
        "-p",
        "--page",
        action="store",
        dest="page",
        type=int,
        default=1,
        help="The results page to show, 1 by default",
    )

    return parser.parse_args()


def main() -> None:
    args = get_args()

    search_vars = vars(args)
    index = search_vars.pop("index", None)
    if search_vars.get("query"):
        search_results = search_bandcamp(**search_vars)

        if index:
            url = search_results[index - 1]["url"]

            print(f"Opening search result number {index}: {url}")
            webbrowser.open(url)
        else:
            print(json.dumps(search_results))
    else:
        url = args.release_url
        pl = GuruMixin()
        if result := pl.get_album_info(url) or pl.get_track_info(url):
            print(json.dumps(result))
        else:
            raise AssertionError("Failed to find a release under the given url")


if __name__ == "__main__":
    main()
