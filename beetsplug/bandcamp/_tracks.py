"""Module with track parsing functionality."""
import itertools as it
import operator as op
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from functools import reduce
from typing import Dict, Iterator, List, Optional, Set

from ordered_set import OrderedSet as ordset

from ._helpers import CATNUM_PAT, PATTERNS, Helpers, JSONDict, _remix_pat

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
TRACK_ALT_PAT = PATTERNS["track_alt"]


@dataclass
class Remix:
    PATTERN = re.compile(rf" *[\[(] *{_remix_pat}[])]", re.I)

    delimited: str
    remixer: str
    remix: str
    by_other_artist: bool

    @classmethod
    def from_name(cls, name: str) -> Optional["Remix"]:
        m = cls.PATTERN.search(name)
        if m:
            remix = m.groupdict()
            remix["delimited"] = m.group().strip()
            remix["remixer"] = remix["remixer"] or ""
            return cls(**remix, by_other_artist="Original" in remix["remix"])
        return None


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
    remix: Optional[Remix] = None

    digi_only: bool = False
    track_alt: Optional[str] = None

    @classmethod
    def from_json(cls, json: JSONDict, delim: str, label: str) -> "Track":
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
            "catalognum": json["name_parts"].get("catalognum", ""),
        }
        return cls(**cls.parse_name(data, json["name_parts"]["clean"], delim, label))

    @staticmethod
    def no_digi_name(name: str) -> str:
        """Return the track title which is clear from digi-only artifacts."""
        return reduce(lambda a, b: b.sub("", a), DIGI_ONLY_PATTERNS, name)

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
        data["json_artist"] = Helpers.clean_name(data["json_artist"])

        digi_only_name = Track.no_digi_name(name)
        data["digi_only"] = digi_only_name != name
        name = digi_only_name

        name = Helpers.clean_name(name).strip().lstrip("-")

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

        remix = Remix.from_name(name)
        if remix:
            data.update(remix=remix)
            name = name.replace(remix.delimited, "").rstrip()

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
    def name(self) -> str:
        name = self._name
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
        if self.remix:
            return f"{self.main_title} {self.remix.delimited}"
        return self.main_title

    @cached_property
    def artist(self) -> str:
        """Take the name, remove the title, ensure it does not duplicate any remixers
        and return the resulting artist.
        """
        artist = self.name[: self.name.rfind(self.main_title)].strip(", -")
        artist = Remix.PATTERN.sub("", artist)
        if self.remix:
            artist = artist.replace(self.remix.remixer, "").strip(" ,")
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
    TITLE_IN_QUOTES = re.compile(r'^(.+[^ -])[ -]+"([^"]+)"$')
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
        names = cls.split_quoted_titles(names)
        delim = cls.track_delimiter(names)
        for track, name in zip(tracks, names):
            track["name_parts"] = {"original": name, "clean": name}
            track["delim"] = delim
        tracks = cls.common_name_parts(tracks, names, delim)
        return cls([Track.from_json(t, delim, Helpers.get_label(meta)) for t in tracks])

    @cached_property
    def first(self) -> Track:
        return self.tracks[0]

    @classmethod
    def split_quoted_titles(cls, names: List[str]) -> List[str]:
        if (
            len(names) > 1
            and cls.TITLE_IN_QUOTES.match(names[0])
            and all(cls.TITLE_IN_QUOTES.match(n) for n in names)
        ):
            return [cls.TITLE_IN_QUOTES.sub(r"\1 - \2", n) for n in names]
        return names

    @staticmethod
    def common_name_parts(
        tracks: List[JSONDict], names: List[str], delim: str
    ) -> List[Dict[str, str]]:
        """Parse track names for parts that require knowledge of the other names.

        1. Split each track name into words
        2. Find the list of words that are common to all tracks
           a. check the *first* and the *last* word for the catalog number
              1. If found, remove it from every track name
           b. check whether tracks start the same way. This indicates an album with
              one unique root title and a couple of its remixes. This is especially
              relevant when the remix is not delimited appropriately.
        Return the catalog number and the new list of names.
        """
        names_tokens = list(map(str.split, names))
        common_words = reduce(op.and_, [ordset(x) for x in names_tokens])
        if not common_words:
            return tracks

        matches = (CATNUM_PAT["anywhere"].search(common_words[i]) for i in [0, -1])
        try:
            cat, word = next(((m.group(1), m.string) for m in matches if m))
        except StopIteration:
            pass
        else:
            for track in tracks:
                track["name_parts"].update(
                    catalognum=cat,
                    clean=track["name_parts"]["clean"].replace(word, "").strip(),
                )

        joined = " ".join(common_words)
        if joined in names:  # it is one of the track names (root title)
            for track in tracks:
                leftover = track["name_parts"]["clean"].replace(joined, "").lstrip()
                # looking for a remix without brackets
                if re.fullmatch(_remix_pat, leftover, re.I):
                    track["name_parts"]["clean"] = f"{joined} ({leftover})"

        return tracks

    @cached_property
    def raw_artists(self) -> List[str]:
        return list(ordset(j.artist for j in self.tracks))

    @cached_property
    def raw_names(self) -> List[str]:
        return [j.name for j in self.tracks]

    @property
    def artists(self) -> List[str]:
        return list(ordset(it.chain(*(j.artists for j in self.tracks))))

    @property
    def remixers(self) -> List[str]:
        return [
            t.remix.remixer
            for t in self.tracks
            if t.remix and not t.remix.by_other_artist
        ]

    @cached_property
    def other_artists(self) -> Set[str]:
        ft = [j.ft for j in self.tracks if j.ft]
        return set(it.chain(self.remixers, ft))

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
                # if this is a remix and the parsed title is part of the albumartist or is one
                # of the track artists, we made a mistake parsing the remix:
                #   it is most probably the edge case where the `main_title` is a legitimate
                #   artist and the track title is something like 'Hello Remix'
                if t.remix and (t.main_title in aartist or t.main_title in artists):
                    t.artist, t.title = t.main_title, t.remix.remix
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
