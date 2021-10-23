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
from functools import partial
from html import unescape
from operator import truth
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set

import requests
from beets import __version__, config, library, plugins
from beets.autotag.hooks import AlbumInfo, TrackInfo
from beets.importer import ImportTask
from beetsplug import fetchart  # type: ignore[attr-defined]
from rich.console import Console

from ._metaguru import DATA_SOURCE, DEFAULT_MEDIA, Metaguru, urlify

console = Console(force_terminal=True, force_interactive=True, highlight=True)

JSONDict = Dict[str, Any]

DEFAULT_CONFIG: JSONDict = {
    "preferred_media": DEFAULT_MEDIA,
    "include_digital_only_tracks": True,
    "search_max": 10,
    "lyrics": False,
    "art": False,
    "exclude_extra_fields": [],
}

SEARCH_URL = "https://bandcamp.com/search?q={0}&page={1}"
ALBUM_URL_IN_TRACK = re.compile(r'inAlbum":{[^}]*"@id":"([^"]*)"')
SEARCH_ITEM_PAT = 'href="(https://[^/]*/{}/[^?]*)'
USER_AGENT = "beets/{} +http://beets.radbox.org/".format(__version__)
ALBUM_SEARCH = "album"
ARTIST_SEARCH = "band"
TRACK_SEARCH = "track"

ADDITIONAL_DATA_MAP: Dict[str, str] = {
    "lyrics": "lyrics",
    "description": "comments",
}


def append_discogs_data(task):

    if not len(task.candidates):
        return

    from beetsplug import discogs

    album = task.candidates[0].info

    pl = discogs.DiscogsPlugin()
    pl.setup()

    label = album.label.split(" ")[0]
    year = album.year
    albumartist = album.artist
    artist = None
    track = None
    if album.albumtype == "single" and not hasattr(album, "tracks"):
        reltitle = album.album
        artist = albumartist
        track = reltitle.split(" - ")[-1]
    else:
        reltitle = re.sub(r" +?[^A-z0-9 ].+$", "", album.album)
        if hasattr(album, "tracks"):
            artist = album.tracks[0].artist
            track = album.tracks[0].title

    print(f"Checking discogs for release: {reltitle}, label: {label}, year: {year}")
    releases = pl.discogs_client.search(release_title=reltitle, label=label, year=year)
    if not len(releases) and artist and track:
        print(f"Checking discogs for track artist: {artist}, track: {track}")
        releases = pl.discogs_client.search(artist=artist, track=track)
    if not len(releases):
        if "various" not in reltitle.casefold():
            print(f"Checking discogs for release: {reltitle}, albumartist: {albumartist}")
            releases = pl.discogs_client.search(
                release_title=reltitle, artist=albumartist
            )
    if len(releases):
        release = vars(releases[0])["data"]
        console.print(release)

        album.discogs_albumid = release["id"]
        catno = release.get("catno")
        if not (catno == "none" or re.match(r"\d+", catno)):
            album.catalognum = catno

        all_genres = set([*(album.genre or "").split(", "), *release["style"]])
        album.genre = ", ".join(filter(truth, sorted(all_genres)))

        # dlabel = release.get("label")[0]
        # if (
        #     not dlabel.startswith("Not On Label")
        #     and album.label.casefold() != dlabel.casefold()
        # ):
        #     album.label = dlabel

        relcountry = release.get("country")
        if album.country == "XW" and relcountry and len(relcountry) == 2:
            album.country = relcountry


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
    return (
        "soundcloud" in clue
        or ".bandcamp." in clue
        or (clue.startswith("http") and ("/album/" in clue or "/track/" in clue))
    )


class BandcampAlbumArt(BandcampRequestsHandler, fetchart.RemoteArtSource):
    NAME = "Bandcamp"
    get_guru = None  # type: Callable[[str], Metaguru]

    def __init__(self, get_guru: Callable, *args) -> None:
        setattr(self, "get_guru", get_guru)
        super().__init__(*args)

    def get(self, album: AlbumInfo, _, paths) -> Iterator[fetchart.Candidate]:
        """Return the url for the cover from the bandcamp album page.
        This only returns cover art urls for bandcamp albums (by id).
        """
        if hasattr(album, "art_source") and album.art_source == DATA_SOURCE:
            self._info("Art cover is already present")
        elif not _from_bandcamp(album.mb_albumid):
            self._info("Not fetching art for a non-bandcamp album: {}", album.mb_albumid)
        else:
            guru = getattr(self, "get_guru")(album.mb_albumid)
            if not guru:
                self._info("Could not obtain the following URL: {}", album.mb_albumid)
            else:
                try:
                    image = guru.image
                except Exception:
                    self._exc("Unexpected parsing error fetching album art")
                yield self._candidate(url=image, match=fetchart.Candidate.MATCH_EXACT)


class BandcampPlugin(BandcampRequestsHandler, plugins.BeetsPlugin):
    _gurucache: Dict[str, Metaguru]

    def __init__(self) -> None:
        super().__init__()
        self.config.add(DEFAULT_CONFIG.copy())

        self.excluded_extra_fields = set(self.config["exclude_extra_fields"].get())
        # self.register_listener("before_choose_candidate", self.append_discogs_data)
        self.register_listener("pluginload", self.loaded)
        self._gurucache = dict()

    def append_discogs_data(self, task: ImportTask) -> None:
        try:
            append_discogs_data(task)
        except Exception:
            console.print_exception(show_locals=True, extra_lines=8)
            exit(1)

    def add_additional_data(self, task: ImportTask) -> None:
        """Import hook for fetching additional data from bandcamp."""
        for item in task.items:
            if _from_bandcamp(item.mb_albumid or item.mb_trackid):
                self._add_additional_data(item)

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
            self._gurucache[url] = Metaguru(
                html,
                self.config["preferred_media"].as_str(),
                self.config["include_digital_only_tracks"].get(),
            )
        return self._gurucache.get(url)

    def loaded(self) -> None:
        """Add our own artsource to the fetchart plugin."""
        # TODO: This is ugly, but i didn't find another way to extend fetchart
        # without declaring a new plugin.
        if self.config["art"]:
            fetchart.ART_SOURCES[DATA_SOURCE] = BandcampAlbumArt
            fetchart.SOURCE_NAMES[BandcampAlbumArt] = DATA_SOURCE
            bandcamp_fetchart = BandcampAlbumArt(
                partial(self.guru), self._log, self.config
            )

            for plugin in plugins.find_plugins():
                if isinstance(plugin, fetchart.FetchArtPlugin):
                    plugin.sources = [bandcamp_fetchart, *plugin.sources]
                    break

    def _cheat_mode(self, item: library.Item, name: str, _type: str) -> str:
        reimport_url: str = getattr(item, f"mb_{_type}id", "")
        if "bandcamp" in reimport_url:
            return reimport_url

        if item.comments.startswith("Visit"):
            match = re.search(r"https:[/a-z0-9.-]+com", item.comments)
            if match:
                url = "{}/{}/{}".format(match.group(), _type, urlify(name))
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
        print(self)
        print(album_id)
        if _from_bandcamp(album_id):
            return self.get_album_info(album_id)
        if "soundcloud" in album_id:
            return self.get_track_info(album_id)

        self._info("Not a bandcamp URL, skipping")
        return None

    def track_for_id(self, track_id: str) -> Optional[TrackInfo]:
        """Fetch a track by its bandcamp ID."""
        print(self)
        print(track_id)
        if _from_bandcamp(track_id) or "soundcloud" in track_id:
            return self.get_track_info(track_id)

        self._info("Not a bandcamp URL, skipping")
        return None

    def handle(self, guru: Metaguru, attr: str, _id: str) -> Any:
        try:
            return getattr(guru, attr)
        except (KeyError, ValueError, AttributeError):
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
        # https://soundcloud.com/paul-copping/the-right-frame-of-mind
        if "/track/" in url:
            match = re.search(r'inAlbum.+(https://[^/]+/album/[^#?"]+)', self._get(url))
            if match:
                url = match.expand(r"\1")
            else:
                return self.get_track_info(url)

        guru = self.guru(url, html=self._get(url))
        return self.handle(guru, "album", url) if guru else None

    def get_track_info(self, url: str) -> Optional[TrackInfo]:
        """Returns a TrackInfo object for a bandcamp track page."""
        if "soundcloud" in url:
            import json

            from beets.autotag import TrackInfo
            from dateutil.parser import isoparse

            data = json.loads(re.search(r"\[\{[^<]+[^;<)]", self._get(url)).group())
            dat = data[-1]["data"]
            user = dat["user"]
            date = isoparse(dat["display_date"])
            artist = user.get("full_name") or user.get("username")
            desc = [
                "Artwork: " + dat["artwork_url"],
                "Description: \n" + dat.get("description"),
                "Visual: " + user["visuals"]["visuals"][0]["visual_url"],
            ]
            return TrackInfo(
                album_id=url,
                album=dat.get("title"),
                albumtype=dat.get("track_format"),
                artist_id=user["permalink_url"],
                albumartist=artist,
                artist=artist,
                track_id=url,
                index=1,
                media="Digital Media",
                data_source="soundcloud",
                data_url=url,
                genre=dat.get("genre") or None,
                title=dat["title"],
                label=dat.get("label_name") or "",
                country=user.get("country_code"),
                comments="\n\n".join(desc),
                length=round(dat["duration"] / 1000),
                day=date.day,
                month=date.month,
                year=date.year,
            )

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


def main() -> int:
    import json
    import os
    import sys

    url = sys.argv[1]
    pl = BandcampPlugin()
    try:
        album = pl.get_album_info(url) or pl.get_track_info(url)
        assert album
    except Exception as exc:
        console.print_exception(
            extra_lines=8, show_locals=True, width=os.environ.get("COLUMNS", 150)
        )
        console.print(vars(pl))
        console.print([*map(vars, pl._gurucache.values())])
        raise exc
    else:
        print(json.dumps(album))


if __name__ == "__main__":
    main()
