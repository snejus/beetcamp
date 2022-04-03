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
from difflib import SequenceMatcher
from html import unescape
from operator import truth
from typing import Any, Dict, Iterable, List, Optional, Sequence

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

SEARCH_URL = "https://bandcamp.com/search?q={}&item_type={}"
ALBUM_URL_IN_TRACK = re.compile(r"inAlbum.+(https://[^/]+/album/[\w-]+)")
USER_AGENT = f"beets/{__version__} +http://beets.radbox.org/"
ALBUM_SEARCH = "album"
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
        # type: (AlbumInfo, plugins.BeetsPlugin, List) -> Iterable[fetchart.Candidate]  # noqa
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
    """Check if the clue is likely to be a bandcamp url.
    We could check whether 'bandcamp' is found in the url, however, we would be ignoring
    cases where the publisher uses their own domain (for example https://eaux.ro) which
    in reality points to their Bandcamp page. Historically, we found that regardless
    of the domain, the rest of the url stays the same, therefore '/album/' or '/track/'
    is what we are looking for in a valid url here.
    """
    return bool(re.match(r"http[^ ]+/(album|track)/", clue))


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

    def _find_url(self, item: library.Item, name: str, _type: str) -> str:
        """If the item has previously been imported, `mb_albumid` (or `mb_trackid`
        for singletons) contains the release url.

        As of 2022 April, Bandcamp purchases (at least in FLAC format) contain string
        *Visit {label_url}* in the `comments` field, therefore we try our luck here.

        If it is found, then the album/track name is converted into a valid url
        representation and appended to the `label_url`. This ends up being the correct
        url except when:
            * album name has been updated on Bandcamp but the file contains the old one
            * album name does not contain a single ascii alphanumeric character
              - in reality, this becomes '--{num}' in the url, where `num` depends on
              the number of previous releases that also did not have any valid alphanums.
              Therefore, we cannot make a reliable guess here.
        """
        url = getattr(item, f"mb_{_type}id", "")
        if _from_bandcamp(url):
            self._info("Fetching the URL attached to the first item, {}", url)
            return url

        match = re.match(r"Visit (https:[\w/.-]+com)", item.comments)
        urlified_name = urlify(name)
        if match and urlified_name:
            label = match.expand(r"\1")
            url = "/".join([label, _type, urlified_name])
            self._info("Trying our guess {} before searching", url)
            return url
        return ""

    def candidates(self, items, artist, album, *_, **__):
        # type: (List[library.Item], str, str, Any, Any) -> Iterable[AlbumInfo]
        """Return a sequence of AlbumInfo objects that match the
        album whose items are provided.
        """
        if items:
            url = self._find_url(items[0], album, ALBUM_SEARCH)
            initial_guess = self.get_album_info(url) if url else None
            if initial_guess:
                return iter([initial_guess])

        results = map(lambda x: x["url"], self._search(album, ALBUM_SEARCH, artist))
        return filter(truth, map(self.get_album_info, results))

    def item_candidates(self, item, artist, title):
        # type: (library.Item, str, str) -> Iterable[TrackInfo]
        """Return a sequence of TrackInfo objects that match the provided item.
        If the track was downloaded directly from bandcamp, it should contain
        a comment saying 'Visit <label-url>' - we look at this first by converting
        title into the format that Bandcamp use.
        """
        url = self._find_url(item, title, TRACK_SEARCH)
        initial_guess = self.get_track_info(url) if url else None
        if initial_guess:
            return iter([initial_guess])

        query = title or item.album

        results = map(lambda x: x["url"], self._search(query, TRACK_SEARCH, artist))
        return filter(truth, map(self.get_track_info, results))

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
        except Exception:  # pylint: disable=broad-except
            url = "https://github.com/snejus/beetcamp/issues/new"
            self._exc("Unexpected error obtaining {}, please report at {}", _id, url)
        return None

    def get_album_info(self, url: str) -> Optional[AlbumInfo]:
        """Return an AlbumInfo object for a bandcamp album page.
        If track url is given by mistake, find and fetch the album url instead.
        """
        html = self._get(url)
        if "/track/" in url:
            match = ALBUM_URL_IN_TRACK.search(html)
            if match:
                url = re.sub(r"/track/.*", match.expand(r"\1"), url)
                html = self._get(url)
        guru = self.guru(url, html=html)
        return self.handle(guru, "album", url) if guru else None

    def get_track_info(self, url: str) -> Optional[TrackInfo]:
        """Returns a TrackInfo object for a bandcamp track page."""
        guru = self.guru(url)
        return self.handle(guru, "singleton", url) if guru else None

    @staticmethod
    def _parse_and_sort_results(html: str, release: str, artist: str) -> List[JSONDict]:
        """Given the html string, find release URLs and artists and sort them
        by similarity.
        similarity = length(longest match between query and result) / length(query)
        When both release name and artist are given, we use the average.
        """
        pat = r"""
(?P<url>https://[^/]+/(album|track)/[\w-]+)[^>]+>
\s*(?P<release>[^\n]+)
.+?\ by\ (?P<artist>[^\n]+)
"""
        pattern = re.compile(pat, re.DOTALL + re.VERBOSE)

        def get_similarity(a: str, b: str) -> float:
            """Return the similarity between two strings normalized to [0, 1]
            with two decimal places.
            """
            match = SequenceMatcher(a=a, b=b).find_longest_match(0, len(a), 0, len(b))
            return round(float(match.size / len(a)), 2)

        results: List[JSONDict] = []
        for block in html.split('class="heading"'):
            match = pattern.search(block)
            if match:
                res = match.groupdict()
                similarity = get_similarity(release, res["release"])
                if artist:
                    similarity += get_similarity(artist.lower(), res["artist"].lower())
                    similarity /= 2
                res["similarity"] = similarity
                results.append(res)
        return sorted(results, key=lambda x: x["similarity"], reverse=True)

    def _search(
        self,
        query: str,
        search_type: str = ALBUM_SEARCH,
        artist: str = "",
        search_max: int = 0,
    ) -> Iterable[JSONDict]:
        """Return an iterator for item URLs of type search_type matching the query.
        Bandcamp search may be unpredictable, therefore the search results get sorted
        regarding their similarity to what's being queried.
        """
        url = SEARCH_URL.format(query, search_type[0])
        self._info("Searching {}s for {}, URL: {}", search_type, query, url)
        html = self._get(url)

        results = self._parse_and_sort_results(html, query, artist)
        search_max = search_max or self.config["search_max"].as_number()
        return results[:search_max]


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
