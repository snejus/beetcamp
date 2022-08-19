"""Module with track parsing functionality."""
import itertools as it
import operator as op
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from functools import reduce
from typing import Iterator, List, Optional, Set, Tuple

from ordered_set import OrderedSet as ordset

from ._helpers import CATNUM_PAT, PATTERNS, Helpers, JSONDict

if sys.version_info.minor > 7:
    from functools import cached_property  # pylint: disable=ungrouped-imports
else:
    from cached_property import cached_property  # type: ignore # pylint: disable=import-error # noqa

_comp = re.compile

DIGI_ONLY_PATTERNS = [
    _comp(r"^(DIGI(TAL)? ?[\d.]+|Bonus\W{2,})\W*"),
    _comp(
        r"[^\w)]+(bandcamp[^-]+|digi(tal)?)(\W*(\W+|only|bonus|exclusive)\W*$)", re.I
    ),
    _comp(r"[^\w)]+(bandcamp exclusive )?bonus( track)?(\]\W*|\W*$)", re.I),
]
DELIMITER_PAT = _comp(r" ([^\w&()+/[\] ]) ")
ELP_ALBUM_PAT = _comp(r"[- ]*\[([^\]]+ [EL]P)\]+")  # Title [Some Album EP]
FT_PAT = _comp(
    r"""
[ ]*                     # all preceding space
((?P<br>[\[(])|\b)       # bracket or word boundary
(ft|feat|featuring)[. ]  # one of the three ft variations
(
    # when it does not start with a bracket, do not allow " - " in it, otherwise
    # we may match full track name
    (?(br)|(?!.* - .*))
    [^]\[()]+     # anything but brackets
)
(?<!mix)\b        # does not end with "mix"
(?(br)[]\)])      # if it started with a bracket, it must end with a closing bracket
[ ]*              # trailing space
    """,
    re.I | re.VERBOSE,
)
REMIXER_PAT = _comp(r" *[\[(] *([^])]+) ((re)?mix|edit|bootleg[^])]+)[])]", re.I)
TRACK_ALT_PAT = PATTERNS["track_alt"]


@dataclass
class Track:
    json_item: JSONDict = field(default_factory=dict)
    track_id: str = ""
    index: Optional[int] = None
    json_artist: str = ""

    _name: str = ""
    ft: str = ""
    album: str = ""
    catalognum: str = ""
    remixer: str = ""
    full_remixer: str = ""

    track_alt: Optional[str] = None

    @classmethod
    def from_json(
        cls, json: JSONDict, name: str, delim: str, catalognum: str, label: str
    ) -> "Track":
        try:
            artist = json["inAlbum"]["byArtist"]["name"]
        except KeyError:
            artist = ""
        artist = artist or json.get("byArtist", {}).get("name", "")
        data = {
            "json_item": json,
            "json_artist": artist,
            "track_id": json["@id"],
            "index": json.get("position"),
            "catalognum": catalognum,
        }
        return cls(**cls.parse_name(data, name, delim, label))

    @staticmethod
    def find_featuring(data: JSONDict) -> JSONDict:
        """Find featuring artist in the track name.

        If the found artist is contained within the remixer, do not do anything.
        If the found artist is among the main artists, remove it from the name but
        do not consider it as a featuring artist.
        Otherwise, strip brackets and spaces and save it in the 'ft' field.
        """
        for _field in "_name", "json_artist":
            m = FT_PAT.search(data[_field])
            if m:
                ft = m.groups()[-1].strip()
                if ft not in data.get("remixer", ""):
                    data[_field] = data[_field].replace(m.group().rstrip(), "")
                    if ft not in data["json_artist"]:
                        data["ft"] = m.group().strip(" ([])")
                    break
        return data

    @staticmethod
    def parse_name(data: JSONDict, name: str, delim: str, label: str) -> JSONDict:
        name = name.replace(f" {delim} ", " - ")

        # remove label from the end of the track name
        # see https://gutterfunkuk.bandcamp.com/album/gutterfunk-all-subject-to-vibes-various-artists-lp  # noqa
        if name.endswith(label):
            name = name.replace(label, "").strip(" -")
        name = Helpers.clean_name(name).strip().lstrip("-")
        data["json_artist"] = Helpers.clean_name(data["json_artist"])

        m = TRACK_ALT_PAT.search(name)
        if m:
            data["track_alt"] = m.group(1).upper()
            name = name.replace(m.group(), "")

        if not data.get("catalognum"):
            # check whether track name contains the catalog number within parens
            # or square brackets
            # see https://objection999x.bandcamp.com/album/eruption-va-obj012
            m = CATNUM_PAT["delimited"].search(name)
            if m:
                data["catalognum"] = m.group(1)
                name = name.replace(m.group(), "").strip()
        name = re.sub(rf"^0*{data.get('index', 0)}(?!\W\d)\W+", "", name)

        m = REMIXER_PAT.search(name)
        if m:
            data.update(remixer=m.group(1), full_remixer=m.group().strip())
            name = name.replace(m.group(), "")

        m = ELP_ALBUM_PAT.search(name)
        if m:
            data["album"] = m.group(1).replace('"', "")
            name = name.replace(m.group(), "")

        data["_name"] = name
        data = Track.find_featuring(data)
        return data

    @cached_property
    def duration(self) -> Optional[int]:
        try:
            h, m, s = map(int, re.findall(r"\d+", self.json_item["duration"]))
        except KeyError:
            return None
        else:
            return h * 3600 + m * 60 + s

    @cached_property
    def lyrics(self) -> str:
        try:
            return self.json_item["recordingOf"]["lyrics"]["text"].replace("\r", "")
        except KeyError:
            return ""

    @cached_property
    def no_digi_name(self) -> str:
        """Return the track title which is clear from digi-only artifacts."""
        return reduce(lambda a, b: b.sub("", a), DIGI_ONLY_PATTERNS, self._name)

    @cached_property
    def digi_only(self) -> bool:
        """Return True if the track is digi-only."""
        return self._name != self.no_digi_name

    @cached_property
    def name(self) -> str:
        name = self.no_digi_name
        if self.json_artist and " - " not in name:
            name = f"{self.json_artist} - {name}"
        return name.strip()

    @cached_property
    def main_title(self) -> str:
        """Split the track name, deduce the title and return it.
        The extra complexity here is to ensure that it does not cut off a title
        that ends with ' - -', like in '(DJ) NICK JERSEY - 202memo - - -'.
        """
        parts = re.split(r" - (?![^\[(]+[])])", self.name)
        if len(parts) == 1:
            parts = self.name.split(" - ")
        main_title = parts[-1]
        for idx, maybe in enumerate(reversed(parts)):
            if not maybe.strip(" -"):
                main_title = " - ".join(parts[-idx - 2 :])
                break
        return main_title

    @cached_property
    def title(self) -> str:
        """Return the main title with the full remixer part appended to it."""
        if self.remixer:
            return self.main_title + " " + self.full_remixer
        return self.main_title

    @cached_property
    def artist(self) -> str:
        """Take the name, remove the title, ensure it does not duplicate any remixers
        and return the resulting artist.
        """
        artist = self.name[: self.name.rfind(self.main_title)].strip(", -")
        artist = REMIXER_PAT.sub("", artist)
        if self.remixer:
            artist = artist.replace(self.remixer, "").strip(" ,")
        return artist.strip(" -")

    @property
    def artists(self) -> List[str]:
        return Helpers.split_artists([self.artist])

    @property
    def info(self) -> JSONDict:
        return {
            "index": self.index,
            "medium_index": self.index,
            "medium": None,
            "track_id": self.track_id,
            "artist": self.artist + (f" {self.ft}" if self.ft else ""),
            "title": self.title,
            "length": self.duration,
            "track_alt": self.track_alt,
            "lyrics": self.lyrics,
            "catalognum": self.catalognum or None,
        }


@dataclass
class Tracks(list):
    tracks: List[Track]

    def __iter__(self) -> Iterator[Track]:
        return iter(self.tracks)

    def __len__(self) -> int:
        return len(self.tracks)

    @classmethod
    def from_json(cls, meta: JSONDict) -> "Tracks":
        try:
            tracks = [{**t, **t["item"]} for t in meta["track"]["itemListElement"]]
        except (TypeError, KeyError):
            tracks = [meta]

        names = [i.get("name", "") for i in tracks]
        delim = cls.track_delimiter(names)
        catalognum, names = cls.common_catalognum(names, delim)
        return cls(
            [
                Track.from_json(t, n, delim, catalognum, Helpers.get_label(meta))
                for n, t in zip(names, tracks)
            ]
        )

    @cached_property
    def first(self) -> Track:
        return self.tracks[0]

    @staticmethod
    def common_catalognum(names: List[str], delim: str) -> Tuple[str, List[str]]:
        """Split each track name into words, find the list of words that are common
        to all tracks, and check the *first* and the *last* word for a catalog number.

        If found, remove that word / catalog number from each track name.
        Return the catalog number and the new list of names.
        """
        names_tokens = list(map(str.split, names))
        common_words = reduce(op.and_, [ordset(x) for x in names_tokens]) - {delim}
        if common_words:
            for word in common_words[0], common_words[-1]:  # type: ignore[index]
                m = CATNUM_PAT["anywhere"].search(word)
                if m:
                    for tokens in names_tokens:
                        tokens.remove(word)
                    return m.group(1), list(map(" ".join, names_tokens))
        return "", names

    @cached_property
    def raw_artists(self) -> List[str]:
        return list(ordset(j.artist for j in self.tracks))

    @cached_property
    def raw_names(self) -> List[str]:
        return [j.name for j in self.tracks]

    @property
    def artists(self) -> List[str]:
        return list(ordset(it.chain(*(j.artists for j in self.tracks))))

    @cached_property
    def other_artists(self) -> Set[str]:
        remixers = [j.remixer for j in self.tracks if j.remixer]
        ft = [j.ft for j in self.tracks if j.ft]
        return set(it.chain(remixers, ft))

    def adjust_artists(self, aartist: str) -> None:
        """Handle some track artist edge cases
        * When artist name is mistaken for the track_alt
        * When artist and title are delimited by '-' without spaces
        * When artist and title are delimited by a UTF-8 dash equivalent
        * Defaulting to the album artist
        """
        track_alts = {t.track_alt for t in self.tracks if t.track_alt}
        artists = [t.artists for t in self.tracks if t.artists]

        for t in [track for track in self.tracks if not track.artist]:
            if t.track_alt and len(track_alts) == 1:  # only one track_alt
                # the only track that parsed a track alt - it's most likely a mistake
                # one artist was confused for a track alt, like 'B2', - reverse this
                t.artist, t.track_alt = t.track_alt, None
            elif len(artists) == len(self) - 1:  # only 1 missing artist
                # this is the only artist that didn't get parsed - relax the rule
                # and try splitting with '-' without spaces
                split = t.title.split("-")
                if len(split) == 1:
                    # attempt to split by another ' ? ' where '?' may be some utf-8
                    # alternative of a dash
                    split = [s for s in DELIMITER_PAT.split(t.title) if len(s) > 1]
                if len(split) > 1:
                    t.artist, t.title = split
            if not t.artist:
                # use the albumartist
                t.artist = aartist

    @staticmethod
    def track_delimiter(names: List[str]) -> str:
        """Return the track parts delimiter that is in effect in the current release.
        In some (rare) situations track parts are delimited by a pipe character
        or some UTF-8 equivalent of a dash.

        This checks every track for the first character (see the regex for exclusions)
        that splits it. The character that splits the most and at least half of
        the tracks is the character we need.

        If no such character is found, or if we have just one track, return a dash '-'.
        """

        def get_delim(string: str) -> str:
            match = DELIMITER_PAT.search(string)
            return match.group(1) if match else "-"

        delim, count = Counter(map(get_delim, names)).most_common(1).pop()
        return delim if (len(names) == 1 or count > len(names) / 2) else "-"
