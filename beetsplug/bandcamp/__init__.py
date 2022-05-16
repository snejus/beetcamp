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
from operator import itemgetter, truth
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests
from beets import __version__, library, plugins
from beets.autotag.hooks import AlbumInfo, TrackInfo
from beetsplug import fetchart  # type: ignore[attr-defined]

from ._metaguru import DATA_SOURCE, Metaguru
from ._search import search_bandcamp

JSONDict = Dict[str, Any]

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
USER_AGENT = f"beets/{__version__} +http://beets.radbox.org/"


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

    def get(self, album, plugin, paths):
        # type: (AlbumInfo, plugins.BeetsPlugin, List) -> Iterable[fetchart.Candidate]  # noqa
        """Return the url for the cover from the bandcamp album page.
        This only returns cover art urls for bandcamp albums (by id).
        """
        url = album.mb_albumid
        if not _from_bandcamp(url):
            self._info("Not fetching art for a non-bandcamp album URL")
        else:
            html = self._get(url)
            if not html:
                self._info("Could not connect to the URL")
            else:
                try:
                    yield self._candidate(
                        url=Metaguru.from_html(html).image,
                        match=fetchart.Candidate.MATCH_EXACT,
                    )
                except (KeyError, AttributeError, ValueError):
                    self._info("Unexpected parsing error fetching album art")


def urlify(pretty_string: str) -> str:
    """Transform a string into bandcamp url."""
    name = pretty_string.lower().replace("'", "").replace(".", "")
    return re.sub("--+", "-", re.sub(r"\W", "-", name, flags=re.ASCII)).strip("-")


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

    def candidates(self, items, artist, album, va_likely, extra_tags=None):
        # type: (List[library.Item], str, str, bool, Any) -> Iterable[AlbumInfo]
        """Return a sequence of AlbumInfo objects that match the
        album whose items are provided or are being searched.
        """
        label = ""
        if items and album == items[0].album and artist == items[0].albumartist:
            label = items[0].label
            url = self._find_url(items[0], album, "album")
            if url:
                initial_guess = self.get_album_info(url)
                if initial_guess:
                    yield from initial_guess
                    return

        if "various" in artist.lower():
            artist = ""

        search = dict(query=album, artist=artist, label=label, search_type="a")
        results = map(itemgetter("url"), self._search(search))
        for res in filter(truth, map(self.get_album_info, results)):
            yield from res

    def item_candidates(self, item, artist, title):
        # type: (library.Item, str, str) -> Iterable[TrackInfo]
        """Return a sequence of TrackInfo objects that match the provided item.
        If the track was downloaded directly from bandcamp, it should contain
        a comment saying 'Visit <label-url>' - we look at this first by converting
        title into the format that Bandcamp use.
        """
        url = self._find_url(item, title, "track")
        label = ""
        if item and title == item.title and artist == item.artist:
            label = item.label
            initial_guess = self.get_track_info(url) if url else None
            if initial_guess:
                yield initial_guess
                return

        search = dict(query=title, artist=artist, label=label, search_type="t")
        results = map(itemgetter("url"), self._search(search))
        yield from filter(truth, map(self.get_track_info, results))

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

    def get_album_info(self, url: str) -> Iterable[AlbumInfo]:
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
        return self.handle(guru, "albums", url) if guru else None

    def get_track_info(self, url: str) -> Optional[TrackInfo]:
        """Returns a TrackInfo object for a bandcamp track page."""
        guru = self.guru(url)
        return self.handle(guru, "singleton", url) if guru else None

    def _search(self, data: JSONDict) -> Iterable[JSONDict]:
        """Return a list of track/album URLs of type search_type matching the query."""
        msg = "Searching {}s for {} using {}"
        self._info(msg, data["search_type"], data["query"], str(data))
        results = search_bandcamp(**data, get=self._get)
        return results[: self.config["search_max"].as_number()]


def get_args() -> Any:
    from argparse import Action, ArgumentParser, Namespace

    parser = ArgumentParser(
        description="""Get bandcamp release metadata from the given <release-url>
or perform bandcamp search with <query>. Anything that does not start with https://
will be assumed to be a query.

Search type flags: -a for albums, -l for labels and artists, -t for tracks.
By default, all types are searched.
"""
    )

    class UrlOrQueryAction(Action):
        def __call__(self, parser, namespace, values, option_string=None):
            val = values
            if val:
                if val.startswith("https://"):
                    target = "release_url"
                else:
                    target = "query"
                    del namespace.release_url
                setattr(namespace, target, val)

    exclusive = parser.add_mutually_exclusive_group()
    exclusive.add_argument(
        "release_url",
        action=UrlOrQueryAction,
        nargs="?",
        help="Release URL, starting with https:// OR",
    )
    exclusive.add_argument(
        "query", action=UrlOrQueryAction, default="", nargs="?", help="Search query"
    )

    common = dict(dest="search_type", action="store_const")
    parser.add_argument("-a", "--album", const="a", help="Search albums", **common)
    parser.add_argument(
        "-l", "--label", const="b", help="Search labels and artists", **common
    )
    parser.add_argument("-t", "--track", const="t", help="Search tracks", **common)

    args = parser.parse_args(namespace=Namespace(search_type=""))
    if not any(vars(args).values()):
        parser.print_help()
        parser.exit()

    return args


def main():
    import json

    args = get_args()
    if args.query:
        result = search_bandcamp(**vars(args))
    else:
        pl = BandcampPlugin()
        result = pl.album_for_id(args.release_url) or pl.track_for_id(args.release_url)
        if not result:
            raise AssertionError("Failed to find a release under the given url")

    print(json.dumps(result))


if __name__ == "__main__":
    main()
