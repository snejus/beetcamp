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
from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import re
from html import unescape
from operator import truth
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set

import requests
import six
from beets import __version__, library, plugins
from beets.autotag.hooks import AlbumInfo, TrackInfo
from beetsplug import fetchart  # type: ignore[attr-defined]

from ._metaguru import DATA_SOURCE, DIGI_MEDIA, Metaguru, urlify

JSONDict = Dict[str, Any]

DEFAULT_CONFIG: JSONDict = {
    "preferred_media": DIGI_MEDIA,
    "include_digital_only_tracks": True,
    "search_max": 10,
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

SEARCH_URL = "https://bandcamp.com/search?q={0}&page={1}"
ALBUM_URL_IN_TRACK = re.compile(r'inAlbum":{[^}]*"@id":"([^"]*)"')
SEARCH_ITEM_PAT = 'href="(https://[^/]*/{}/[^?]*)'
USER_AGENT = f"beets/{__version__} +http://beets.radbox.org/"
ALBUM_SEARCH = "album"
ARTIST_SEARCH = "band"
TRACK_SEARCH = "track"


class BandcampRequestsHandler:
    """A class that provides an ability to make requests and handles failures."""

    _log: logging.Logger

    def _exc(self, msg_template: str, *args: Sequence[str]) -> None:
        self._log.log(logging.WARNING, msg_template, *args, exc_info=True)

    def _info(self, msg_template: str, *args: Sequence[str]) -> None:
        self._log.log(logging.DEBUG, msg_template, *args, exc_info=False)

    def _get(self, url: str) -> str:
        """Return text contents of the url response."""
        headers = {"User-Agent": USER_AGENT}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except requests.exceptions.RequestException:
            self._info("Error while fetching URL: {}", url)
            return ""
        return unescape(response.text)


class BandcampAlbumArt(BandcampRequestsHandler, fetchart.RemoteArtSource):
    NAME = "Bandcamp"

    def get(self, album, plugin, paths):
        # type: (AlbumInfo, plugins.BeetsPlugin, List) -> Iterator[fetchart.Candidate]  # noqa
        """Return the url for the cover from the bandcamp album page.
        This only returns cover art urls for bandcamp albums (by id).
        """
        # TODO: Make this configurable
        if hasattr(album, "art_source") and album.art_source == DATA_SOURCE:
            url = album.mb_albumid
            if isinstance(url, six.string_types) and DATA_SOURCE in url:
                html = self._get(url)
                if html:
                    try:
                        yield self._candidate(
                            url=self.guru(html).image,
                            match=fetchart.Candidate.MATCH_EXACT,
                        )
                    except (KeyError, AttributeError, ValueError):
                        self._info("Unexpected parsing error fetching album art")
                else:
                    self._info("Could not connect to the URL")
            else:
                self._info("Not fetching art for a non-bandcamp album")
        else:
            self._info("Art cover is already present")


def _from_bandcamp(clue: str) -> bool:
    return ".bandcamp." in clue or (
        clue.startswith("http") and ("/album/" in clue or "/track/" in clue)
    )


class BandcampPlugin(BandcampRequestsHandler, plugins.BeetsPlugin):
    _gurucache: Dict[str, Metaguru]

    def __init__(self) -> None:
        super().__init__()
        self.config.add(DEFAULT_CONFIG.copy())

        self.register_listener("pluginload", self.loaded)
        self._gurucache = {}

    def guru(self, url: str, html: Optional[str] = None) -> Optional[Metaguru]:
        """Return cached guru. If there isn't one, fetch the url if html isn't
        already given, initialise guru and add it to the cache. This way they
        can be re-used by separate import stages.
        """
        if url in self._gurucache:
            return self._gurucache[url]
        if not html:
            html = self._get(url)
        if html:
            self._gurucache[url] = Metaguru.from_html(html, self.config.flatten())
        return self._gurucache.get(url)

    def loaded(self) -> None:
        """Add our own artsource to the fetchart plugin."""
        # TODO: This is ugly, but i didn't find another way to extend fetchart
        # without declaring a new plugin.
        if self.config["art"]:
            fetchart.ART_SOURCES[DATA_SOURCE] = BandcampAlbumArt
            fetchart.SOURCE_NAMES[BandcampAlbumArt] = DATA_SOURCE
            bandcamp_fetchart = BandcampAlbumArt(self._log, self.config)

            for plugin in plugins.find_plugins():
                if isinstance(plugin, fetchart.FetchArtPlugin):
                    plugin.sources = [bandcamp_fetchart, *plugin.sources]
                    break

    def _cheat_mode(self, item: library.Item, name: str, _type: str) -> str:
        reimport_url: str = getattr(item, f"mb_{_type}id", "")
        if "bandcamp" in reimport_url:
            return reimport_url

        if item.comments.startswith("Visit"):
            match = re.search(r"https:[/a-z.-]+com", item.comments)
            if match:
                url = f"{match.group()}/{_type}/{urlify(name)}"
                self._info("Trying our guess {} before searching", url)
                return url
        return ""

    def candidates(self, items, artist, album, va_likely, extra_tags=None):
        # type: (List[library.Item], str, str, bool, Optional[JSONDict]) -> Iterator[AlbumInfo]  # noqa
        """Return a sequence of AlbumInfo objects that match the
        album whose items are provided.
        """
        if items:
            initial_url = self._cheat_mode(items[0], album, ALBUM_SEARCH)
            initial_guess = self.get_album_info(initial_url) if initial_url else None
            if initial_guess:
                return iter([initial_guess])

        return filter(truth, map(self.get_album_info, self._search(album, ALBUM_SEARCH)))

    def item_candidates(self, item, artist, title):
        # type: (library.Item, str, str) -> Iterator[TrackInfo]
        """Return a sequence of TrackInfo objects that match the provided item.
        If the track was downloaded directly from bandcamp, it should contain
        a comment saying 'Visit <label-url>' - we look at this first by converting
        title into the format that Bandcamp use.
        """
        initial_url = self._cheat_mode(item, title, TRACK_SEARCH)
        initial_guess = self.get_track_info(initial_url) if initial_url else None
        if initial_guess:
            return iter([initial_guess])

        query = title or item.album or artist
        return filter(truth, map(self.get_track_info, self._search(query, TRACK_SEARCH)))

    def album_for_id(self, album_id: str) -> Optional[AlbumInfo]:
        """Fetch an album by its bandcamp ID."""
        if _from_bandcamp(album_id):
            return self.get_album_info(album_id)

        self._info("Not a bandcamp URL, skipping")
        return None

    def track_for_id(self, track_id: str) -> Optional[TrackInfo]:
        """Fetch a track by its bandcamp ID."""
        if _from_bandcamp(track_id):
            return self.get_track_info(track_id)

        self._info("Not a bandcamp URL, skipping")
        return None

    def handle(self, guru: Metaguru, attr: str, _id: str) -> Any:
        try:
            return getattr(guru, attr)
        except (KeyError, ValueError, AttributeError, IndexError):
            self._info("Failed obtaining {}", _id)
            return None
        except Exception:  # pylint: disable=broad-except
            url = "https://github.com/snejus/beetcamp/issues/new"
            self._exc("Unexpected error obtaining {}, please report at {}", _id, url)
            return None

    def get_album_info(self, url: str) -> Optional[AlbumInfo]:
        """Return an AlbumInfo object for a bandcamp album page.
        If track url is given by mistake, find and fetch the album url instead.
        """
        guru = self.guru(url, html=self._get(url))
        return self.handle(guru, "album", url) if guru else None

    def get_track_info(self, url: str) -> Optional[TrackInfo]:
        """Returns a TrackInfo object for a bandcamp track page."""
        guru = self.guru(url)
        return self.handle(guru, "singleton", url) if guru else None

    def _search(self, query: str, search_type: str = ALBUM_SEARCH) -> Iterator[str]:
        """Return an iterator for item URLs of type search_type matching the query."""
        max_urls = self.config["search_max"].as_number()
        urls: Set[str] = set()

        page = 1
        html = "page=1"
        pattern = SEARCH_ITEM_PAT.format(search_type)

        def next_page_exists() -> bool:
            return bool(re.search(rf"page={page}", html))

        self._info("Searching {}s for {}", search_type, query)
        while next_page_exists():
            self._info("Page {}", str(page))
            html = self._get(SEARCH_URL.format(query, page))

            for match in re.finditer(pattern, html or ""):
                if len(urls) == max_urls:
                    break
                url = match.groups()[0]
                if url not in urls:
                    urls.add(url)
                    yield url
            else:
                self._info("{} total URLs", str(len(urls)))
                page += 1
                continue
            break


def main():
    import json
    import sys

    try:
        url = sys.argv[1]
    except IndexError as exc:
        raise IndexError("bandcamp url is required") from exc
    pl = BandcampPlugin()
    album = pl.album_for_id(url) or pl.track_for_id(url)
    if not album:
        raise AssertionError("Failed to find a release under the given url")

    print(json.dumps(album))


if __name__ == "__main__":
    main()
