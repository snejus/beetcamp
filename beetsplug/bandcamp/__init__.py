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
import sys
from functools import partial
from operator import itemgetter
from typing import TYPE_CHECKING, Any

import httpx
from beets import config as beets_config
from beets import plugins
from beets.util import cached_classproperty as beets_cached_classproperty

from beetsplug import fetchart  # type: ignore[attr-defined]

from .helpers import NEW_METADATA_PLUGIN_CLASS, cached_patternprop
from .http import http_get_text, urlify
from .metaguru import Metaguru
from .search import search_bandcamp

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from re import Match, Pattern
    from typing import ClassVar, TypedDict, Literal

    from beets.autotag.hooks import AlbumInfo, TrackInfo
    from beets.library import Album, Item
    from confuse import ConfigView
    from typing_extensions import TypeAlias

    from .helpers import cached_classproperty
    from .search import SearchType

    class GenreDict(TypedDict):
        capitalize: bool
        maximum: int
        mode: str
        always_include: list[str]

    class ConfigDict(TypedDict):
        include_digital_only_tracks: bool
        search_max: int
        art: bool
        exclude_extra_fields: list[str]
        genre: GenreDict
        comments_separator: str
        truncate_comments: bool

    JSONDict: TypeAlias = dict[str, Any]
    CandidateType: TypeAlias = Literal["album", "track"]


if not sys.version_info < (3, 12):
    from typing import override  # pyright: ignore[reportUnreachable]
else:
    from typing_extensions import override

if not NEW_METADATA_PLUGIN_CLASS:
    from beets.plugins import BeetsPlugin as MetadataSourcePlugin
else:
    from beets.metadata_plugins import MetadataSourcePlugin


DEFAULT_CONFIG: ConfigDict = {
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


class BandcampRequestsHandler:
    """A class that provides an ability to make requests and handles failures."""

    BANDCAMP_URL_PAT: cached_classproperty[Pattern[str]] = cached_patternprop(
        r"http[^ ]+/(album|track)/"
    )

    def __init__(self, log: logging.Logger, config: ConfigView) -> None:
        self._log: logging.Logger = log
        self.config: ConfigView = config

    @classmethod
    def from_bandcamp(cls, clue: str) -> bool:
        """Check if the clue is likely to be a bandcamp url.

        We could check whether 'bandcamp' is found in the url, however, we would be
        ignoring cases where the publisher uses their own domain (for example
        https://eaux.ro) which in reality points to their Bandcamp page. Historically,
        we found that regardless of the domain, the rest of the url stays the same,
        therefore '/album/' or '/track/' is what we are looking for in a valid url here.
        """
        return bool(cls.BANDCAMP_URL_PAT.match(clue))

    def _exc(self, msg_template: str, *args: object) -> None:
        self._log.log(logging.WARNING, msg_template, *args, exc_info=True)

    def _info(self, msg_template: str, *args: object) -> None:
        self._log.log(logging.DEBUG, msg_template, *args, exc_info=False)

    def _get(self, url: str) -> str:
        """Return text contents of the url response."""
        try:
            return http_get_text(url)
        except httpx.HTTPError as e:
            self._info("{}", e)
            return ""

    def guru(self, url: str) -> Metaguru | None:
        try:
            return Metaguru.from_html(html=self._get(url), config=self.config.flatten())
        except (KeyError, ValueError, AttributeError, IndexError) as e:
            self._info("Failed obtaining {}: {}", url, e)
        except Exception:  # pylint: disable=broad-except
            i_url: str = "https://github.com/snejus/beetcamp/issues/new"
            self._exc("Unexpected error obtaining {}, please report at {}", url, i_url)

        return None


class BandcampAlbumArt(fetchart.RemoteArtSource):
    NAME: ClassVar[str] = "Bandcamp"
    ID: ClassVar[str] = NAME

    def __init__(
        self, log: logging.Logger, config: ConfigView, match_by: list[str] | None = None
    ) -> None:
        super().__init__(log=log, config=config, match_by=match_by)
        self.requests_handler: BandcampRequestsHandler = BandcampRequestsHandler(
            log=self._log, config=self._config
        )

    @override
    def get(
        self,
        album: Album,
        plugin: fetchart.FetchArtPlugin | None,
        paths: None | Sequence[bytes],
    ) -> Iterator[fetchart.Candidate]:
        """Return the url for the cover from the bandcamp album page.

        This only returns cover art urls for bandcamp albums (by id).
        """
        url: str = album.mb_albumid
        if not self.requests_handler.from_bandcamp(clue=url):
            self.requests_handler._info("Not fetching art for a non-bandcamp album URL")
        elif (guru := self.requests_handler.guru(url=url)) and (image := guru.image):
            yield self._candidate(url=image)


class BandcampPlugin(MetadataSourcePlugin):
    MAX_COMMENT_LENGTH: int = 4047
    ALBUM_SLUG_IN_TRACK: cached_classproperty[Pattern[str]] = cached_patternprop(
        pattern=r'(?<=<a id="buyAlbumLink" href=")[^"]+'
    )
    LABEL_URL_IN_COMMENT: cached_classproperty[Pattern[str]] = cached_patternprop(
        pattern=r"Visit (https:[\w/.-]+\.[a-z]+)"
    )

    def __init__(self) -> None:
        super().__init__()
        self.config.add(DEFAULT_CONFIG.copy())

        if self.config["truncate_comments"].get():
            self.register_listener("album_imported", self.adjust_comments_field)

        if self.config["art"]:
            self.register_listener("pluginload", self.loaded)
        self.requests_handler: BandcampRequestsHandler = BandcampRequestsHandler(
            log=self._log, config=self.config
        )

    @beets_cached_classproperty
    @override
    def data_source(self) -> str:
        return super().data_source.lower()

    def adjust_comments_field(self, album: Album) -> None:  # noqa: ARG002
        """If the comments field is too long, store it as album flex attr.

        Keep the first 4000 characters in the item and store the full comment as
        a flexible attribute on the album.

        This is relevant for MPD users: mpc seems to crash trying to read comments
        longer than 4047 characters (mpd 0.23.15).
        """
        items: list[Item] = list(album.items())
        comments: bytes = (items[0].comments or "").encode()
        if len(comments) > self.MAX_COMMENT_LENGTH:
            self.requests_handler._info(
                "Truncating comments for items in album {}", album
            )
            album.comments = comments
            album.store()
            truncated: str = f"{comments[: self.MAX_COMMENT_LENGTH - 3].decode()}..."
            item: Item
            for item in items:
                item.comments = truncated
                item.store()

    def loaded(self) -> None:
        """Add our own artsource to the fetchart plugin."""
        plugin: plugins.BeetsPlugin
        for plugin in plugins.find_plugins():
            if isinstance(plugin, fetchart.FetchArtPlugin):
                if isinstance(fetchart.ART_SOURCES, set):
                    fetchart.ART_SOURCES.add(BandcampAlbumArt)
                else:
                    fetchart.ART_SOURCES[self.data_source] = BandcampAlbumArt
                    fetchart.SOURCE_NAMES[BandcampAlbumArt] = self.data_source
                    fetchart.SOURCES_ALL.append(self.data_source)
                bandcamp_fetchart: BandcampAlbumArt = BandcampAlbumArt(
                    log=self._log, config=self.config, match_by=None
                )
                plugin.sources = [bandcamp_fetchart, *plugin.sources]
                break

    @classmethod
    def parse_label_url(cls, text: str) -> str | None:
        return m[1] if (m := cls.LABEL_URL_IN_COMMENT.search(text)) else None

    def _find_url_in_item(self, item: Item, name: str, type_: CandidateType) -> str:
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
        url: str
        if (
            url := getattr(item, f"mb_{type_}id", "")
        ) and self.requests_handler.from_bandcamp(clue=url):
            self.requests_handler._info(
                "Fetching the URL attached to the first item, {}", url
            )
            return url

        label_url: str | None
        if (label_url := self.parse_label_url(text=item.comments)) and (
            urlified_name := urlify(pretty_string=name)
        ):
            url = f"{label_url}/{type_}/{urlified_name}"
            self.requests_handler._info("Trying our guess {} before searching", url)
            return url
        return ""

    @override
    def candidates(
        self,
        items: Sequence[Item],
        artist: str,
        album: str,
        va_likely: bool,
    ) -> Iterable[AlbumInfo]:
        """Return a sequence of album candidates matching given artist and album."""
        item: Item = items[0]
        url: str
        initial_guess: list[AlbumInfo] | None
        if (
            items
            and album == item.album
            and artist == item.albumartist
            and (url := self._find_url_in_item(item=item, name=album, type_="album"))
            and (initial_guess := self.get_album_info(url))
        ):
            yield from initial_guess
            return

        name: str
        search_type: str
        if (va_likely or "various" in artist.lower()) and (
            # user is not searching for anything specific (default search)
            item.album == album and item.artist == artist
        ):
            name, artist = item.title, item.artist
            search_type = "t"
        else:
            name = album
            search_type = "a"

        search: dict[str, str] = {
            "artist": artist,
            "name": name,
        }

        albums: list[AlbumInfo] | None
        for url in map(
            itemgetter("url"),
            self._search(query=None, search_type=search_type, page=None, **search),
        ):
            if albums := self.get_album_info(url):
                yield from albums

    @override
    def item_candidates(
        self, item: Item, artist: str, title: str
    ) -> Iterable[TrackInfo]:
        """Return a sequence of singleton candidates matching given artist and title."""
        url: str
        initial_guess: TrackInfo | None
        if (
            item
            and title == item.title
            and artist == item.artist
            and (url := self._find_url_in_item(item=item, name=title, type_="track"))
            and (initial_guess := self.get_track_info(url=url))
        ):
            yield initial_guess
            return

        search: dict[str, str] = {"artist": artist, "name": title}
        results: map[str] = map(
            itemgetter("url"),
            self._search(query=None, search_type="t", page=None, **search),
        )
        yield from filter(None, map(self.get_track_info, results))

    @override
    def album_for_id(self, album_id: str) -> AlbumInfo | None:
        """Fetch an album by its bandcamp ID."""
        if not self.requests_handler.from_bandcamp(clue=album_id):
            self.requests_handler._info("Not a bandcamp URL, skipping")
            return None

        albums: list[AlbumInfo] | None = self.get_album_info(url=album_id)
        if not albums:
            return None

        if len(albums) > 1:
            # get the preferred media
            preferred: list[str] = beets_config["match"]["preferred"]["media"].get(
                template=list
            )
            pref_to_idx: dict[str, int] = dict(zip(preferred, range(len(preferred))))
            albums = sorted(
                albums,
                key=lambda x: pref_to_idx.get(media, 100)
                if (media := x.media)
                else 100,
            )
        return albums[0]

    @override
    def track_for_id(self, track_id: str) -> TrackInfo | None:
        """Fetch a track by its bandcamp ID."""
        if self.requests_handler.from_bandcamp(clue=track_id):
            return self.get_track_info(url=track_id)

        self.requests_handler._info("Not a bandcamp URL, skipping")
        return None

    def get_album_info(self, url: str) -> list[AlbumInfo] | None:
        """Return an AlbumInfo object for a bandcamp album page.

        If track url is given by mistake, find and fetch the album url instead.
        """
        html: str = self.requests_handler._get(url)
        m: Match[str] | None
        if html and "/track/" in url and (m := self.ALBUM_SLUG_IN_TRACK.search(html)):
            label_url: str = url.split(r"/track/")[0]
            url = f"{label_url}{m[0]}"

        return guru.albums if (guru := self.requests_handler.guru(url)) else None

    def get_track_info(self, url: str) -> TrackInfo | None:
        """Return a TrackInfo object for a bandcamp track page."""
        return guru.singleton if (guru := self.requests_handler.guru(url)) else None

    def _search(
        self,
        query: str | None = None,
        search_type: SearchType | None = None,
        page: int | None = None,
        **kwargs: str,
    ) -> Iterable[JSONDict]:
        """Return a list of track/album URLs of type search_type matching the query."""
        self.requests_handler._info(
            "Searching releases for {} - {}", kwargs["artist"], kwargs["name"]
        )
        results = search_bandcamp(
            query=query,
            search_type=search_type,
            page=page,
            get=self.requests_handler._get,
            **kwargs,
        )
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
        @override
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
    _ = exclusive.add_argument(
        "release_url",
        action=UrlOrQueryAction,
        nargs="?",
        help="Release URL, starting with https:// OR",
    )
    _ = exclusive.add_argument(
        "query", action=UrlOrQueryAction, default="", nargs="?", help="Search query"
    )

    store_const = partial(
        parser.add_argument, dest="search_type", action="store_const", default=""
    )
    _ = store_const("-a", "--album", const="a", help="Search albums")
    _ = store_const("-l", "--label", const="b", help="Search labels and artists")
    _ = store_const("-t", "--track", const="t", help="Search tracks")
    _ = parser.add_argument(
        "-o",
        "--open",
        action="store",
        dest="index",
        type=int,
        help="Open search result indexed by INDEX in the browser",
    )
    _ = parser.add_argument(
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
    import json

    args = get_args()

    search_vars = vars(args)
    index = search_vars.pop("index", None)
    if search_vars.get("query"):
        search_results = search_bandcamp(**search_vars)

        if index:
            url = search_results[index - 1]["url"]

            import webbrowser

            print(f"Opening search result number {index}: {url}")
            webbrowser.open(url)
        else:
            print(json.dumps(search_results))
    else:
        pl = BandcampPlugin()
        pl._log.setLevel(10)
        url = args.release_url
        if result := pl.get_album_info(args.release_url) or pl.get_track_info(url):
            print(json.dumps(result))
        else:
            raise AssertionError("Failed to find a release under the given url")


if __name__ == "__main__":
    main()
