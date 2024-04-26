# beetcamp, Copyright (C) 2021 Šarūnas Nejus. Licensed under the GPLv2 or later.
# Based on beets-bandcamp: Copyright (C) 2015 Ariel George: Original implementation
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; version 2.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

"""Adds bandcamp album search support to the autotagger."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from functools import lru_cache, partial
from html import unescape
from itertools import chain
from operator import itemgetter
from typing import TYPE_CHECKING, Any, Dict, Iterable, Iterator, List, Literal, Sequence

import requests
from beets import IncludeLazyConfig, __version__, config, library, plugins

from beetsplug import fetchart  # type: ignore[attr-defined]

from .metaguru import Metaguru
from .search import search_bandcamp

if TYPE_CHECKING:
    from beets.autotag.hooks import AlbumInfo, TrackInfo

JSONDict = Dict[str, Any]
CandidateType = Literal["album", "track"]

DEFAULT_CONFIG: JSONDict = {
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
}

ALBUM_URL_IN_TRACK = re.compile(r'<a id="buyAlbumLink" href="([^"]+)')
LABEL_URL_IN_COMMENT = re.compile(r"Visit (https:[\w/.-]+com)")
USER_AGENT = f"beets/{__version__} +http://beets.radbox.org/"


@lru_cache(maxsize=None)
def get_response(url: str) -> requests.Response:
    return requests.get(url, headers={"User-Agent": USER_AGENT})


class BandcampRequestsHandler:
    """A class that provides an ability to make requests and handles failures."""

    _log: logging.Logger
    config: IncludeLazyConfig

    def _exc(self, msg_template: str, *args: Sequence[str]) -> None:
        self._log.log(logging.WARNING, msg_template, *args, exc_info=True)

    def _info(self, msg_template: str, *args: Sequence[str]) -> None:
        self._log.log(logging.DEBUG, msg_template, *args, exc_info=False)

    def _get(self, url: str) -> str:
        """Return text contents of the url response."""
        response = get_response(url)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            self._info("URL Not found: {}", url)
            return ""
        return unescape(response.text)

    def guru(self, url: str) -> Metaguru:
        return Metaguru.from_html(self._get(url), config=self.config.flatten())

    @contextmanager
    def handle_error(self, url: str) -> Iterator[Any]:
        """Return Metaguru for the given URL."""
        try:
            yield
        except (KeyError, ValueError, AttributeError, IndexError):
            self._info("Failed obtaining {}", url)
        except Exception:  # pylint: disable=broad-except
            i_url = "https://github.com/snejus/beetcamp/issues/new"
            self._exc("Unexpected error obtaining {}, please report at {}", url, i_url)


def _from_bandcamp(clue: str) -> bool:
    """Check if the clue is likely to be a bandcamp url.

    We could check whether 'bandcamp' is found in the url, however, we would be ignoring
    cases where the publisher uses their own domain (for example https://eaux.ro) which
    in reality points to their Bandcamp page. Historically, we found that regardless
    of the domain, the rest of the url stays the same, therefore '/album/' or '/track/'
    is what we are looking for in a valid url here.
    """
    return bool(re.match(r"http[^ ]+/(album|track)/", clue))


class BandcampAlbumArt(BandcampRequestsHandler, fetchart.RemoteArtSource):
    NAME = "Bandcamp"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.config = self._config

    def get(self, album: AlbumInfo, *_: Any) -> Iterable[fetchart.Candidate]:
        """Return the url for the cover from the bandcamp album page.

        This only returns cover art urls for bandcamp albums (by id).
        """
        url = album.mb_albumid
        if not _from_bandcamp(url):
            self._info("Not fetching art for a non-bandcamp album URL")
        else:
            with self.handle_error(url):
                if image := self.guru(url).image:
                    yield self._candidate(
                        url=image, match=fetchart.Candidate.MATCH_EXACT
                    )


def urlify(pretty_string: str) -> str:
    """Transform a string into bandcamp url."""
    name = pretty_string.lower().replace("'", "").replace(".", "")
    return re.sub("--+", "-", re.sub(r"\W", "-", name, flags=re.ASCII)).strip("-")


class BandcampPlugin(BandcampRequestsHandler, plugins.BeetsPlugin):
    beets_config: IncludeLazyConfig

    def __init__(self) -> None:
        super().__init__()
        self.beets_config = config
        self.config.add(DEFAULT_CONFIG.copy())

        if self.config["art"]:
            self.register_listener("pluginload", self.loaded)

    @property
    def data_source(self) -> str:
        return "bandcamp"

    def loaded(self) -> None:
        """Add our own artsource to the fetchart plugin."""
        for plugin in plugins.find_plugins():
            if isinstance(plugin, fetchart.FetchArtPlugin):
                fetchart.ART_SOURCES[self.data_source] = BandcampAlbumArt
                fetchart.SOURCE_NAMES[BandcampAlbumArt] = self.data_source
                fetchart.SOURCES_ALL.append(self.data_source)
                bandcamp_fetchart = BandcampAlbumArt(self._log, self.config)
                plugin.sources = [bandcamp_fetchart, *plugin.sources]
                break

    def _find_url_in_item(
        self, item: library.Item, name: str, _type: CandidateType
    ) -> str:
        """Try to extract release URL from the library item.

        If the item has previously been imported, `mb_albumid` (or `mb_trackid`
        for singletons) contains the release url.

        As of 2022 April, Bandcamp purchases (at least in FLAC format) contain string
        *Visit {label_url}* in the `comments` field, therefore we try our luck here.

        If it is found, then the album/track name is converted into a valid url
        representation and appended to the `label_url`. This ends up being the correct
        url except when:
            * album name has been updated on Bandcamp but the file contains the old one
            * album name does not contain a single ascii alphanumeric character
              - in reality, this becomes '--{num}' in the url, where `num` depends on
              the number of previous releases that also did not have any valid
              alphanums. Therefore, we cannot make a reliable guess here.
        """
        url = getattr(item, f"mb_{_type}id", "")
        if _from_bandcamp(url):
            self._info("Fetching the URL attached to the first item, {}", url)
            return url

        if (m := LABEL_URL_IN_COMMENT.match(item.comments)) and (
            urlified_name := urlify(name)
        ):
            label = m.group(1)
            url = f"{label}/{_type}/{urlified_name}"
            self._info("Trying our guess {} before searching", url)
            return url
        return ""

    def candidates(
        self, items: List[library.Item], artist: str, album: str, *_: Any, **__: Any
    ) -> Iterable[AlbumInfo]:
        """Return a sequence of album candidates matching given artist and album."""
        label = ""
        if items and album == items[0].album and artist == items[0].albumartist:
            label = items[0].label
            url = self._find_url_in_item(items[0], album, "album")
            if url:
                initial_guess = self.get_album_info(url)
                if initial_guess:
                    yield from initial_guess
                    return

        if "various" in artist.lower():
            artist = ""

        search = {"query": album, "artist": artist, "label": label, "search_type": "a"}
        results = map(itemgetter("url"), self._search(search))
        yield from chain.from_iterable(filter(None, map(self.get_album_info, results)))

    def item_candidates(
        self, item: library.Item, artist: str, title: str
    ) -> Iterable[TrackInfo]:
        """Return a sequence of singleton candidates matching given artist and title."""
        url = self._find_url_in_item(item, title, "track")
        label = ""
        if item and title == item.title and artist == item.artist:
            label = item.label
            initial_guess = self.get_track_info(url) if url else None
            if initial_guess:
                yield initial_guess
                return

        search = {"query": title, "artist": artist, "label": label, "search_type": "t"}
        results = map(itemgetter("url"), self._search(search))
        yield from filter(None, map(self.get_track_info, results))

    def album_for_id(self, album_id: str) -> AlbumInfo | None:
        """Fetch an album by its bandcamp ID."""
        if not _from_bandcamp(album_id):
            self._info("Not a bandcamp URL, skipping")
            return None

        albums = self.get_album_info(album_id)
        if not albums:
            return None

        if len(albums) > 1:
            # get the preferred media
            preferred = self.beets_config["match"]["preferred"]["media"].get()
            pref_to_idx = dict(zip(preferred, range(len(preferred))))
            albums = sorted(albums, key=lambda x: pref_to_idx.get(x.media, 100))
        return albums[0]

    def track_for_id(self, track_id: str) -> TrackInfo | None:
        """Fetch a track by its bandcamp ID."""
        if _from_bandcamp(track_id):
            return self.get_track_info(track_id)

        self._info("Not a bandcamp URL, skipping")
        return None

    def get_album_info(self, url: str) -> List[AlbumInfo] | None:
        """Return an AlbumInfo object for a bandcamp album page.

        If track url is given by mistake, find and fetch the album url instead.
        """
        html = self._get(url)
        if html and "/track/" in url:
            m = ALBUM_URL_IN_TRACK.search(html)
            if m:
                url = re.sub(r"/track/.*", m.expand(r"\1"), url)

        with self.handle_error(url):
            return self.guru(url).albums

    def get_track_info(self, url: str) -> TrackInfo | None:
        """Return a TrackInfo object for a bandcamp track page."""
        with self.handle_error(url):
            return self.guru(url).singleton

    def _search(self, data: JSONDict) -> Iterable[JSONDict]:
        """Return a list of track/album URLs of type search_type matching the query."""
        msg = "Searching {}s for {} using {}"
        self._info(msg, data["search_type"], data["query"], str(data))
        results = search_bandcamp(**data, get=self._get)
        return results[: self.config["search_max"].as_number()]


def get_args() -> Any:
    from argparse import Action, ArgumentParser

    if TYPE_CHECKING:
        from argparse import Namespace

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
            parser: ArgumentParser,
            namespace: Namespace,
            values: Any,
            option_string: str | None = None,
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

    return parser.parse_args()


def main() -> None:
    import json

    args = get_args()

    search_vars = vars(args)
    index = search_vars.pop("index", None)
    if search_vars.get("query"):
        search_results = search_bandcamp(**search_vars)

        if index:
            try:
                url = search_results[index - 1]["url"]
            except IndexError as e:
                raise Exception("Specified index could not be found") from e

            import webbrowser

            print(f"Opening search result number {index}: {url}")
            webbrowser.open(url)
        else:
            print(json.dumps(search_results))
    else:
        pl = BandcampPlugin()
        pl._log.setLevel(10)
        url = args.release_url
        result = pl.get_album_info(args.release_url) or pl.get_track_info(url)
        if not result:
            raise AssertionError("Failed to find a release under the given url")

        print(json.dumps(result))


if __name__ == "__main__":
    main()
