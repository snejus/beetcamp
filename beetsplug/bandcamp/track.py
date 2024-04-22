"""Module with a single track parsing functionality."""

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Dict, List, Optional, Tuple

from .helpers import CATNUM_PAT, PATTERNS, REMIX, Helpers, JSONDict

digiwords = r"""
    # must contain at least one of
    ([ -]?  # delimiter
        (bandcamp|digi(tal)?|exclusive|bonus|bns|unreleased)
    )+
    # and may be followed by
    (\W(track|only|tune))*
    """
DIGI_ONLY_PATTERN = re.compile(
    rf"""
(\s|[^][()\w])*  # space or anything that is not a parens or an alphabetical char
(
      (^{digiwords}[.:\d\s]+\s)     # begins with 'Bonus.', 'Bonus 1.' or 'Bonus :'
 | [\[(]{digiwords}[\])]\W*         # delimited by brackets, '[Bonus]', '(Bonus) -'
 |   [*]{digiwords}[*]?             # delimited by asterisks, '*Bonus', '*Bonus*'
 |      {digiwords}[ ]-             # followed by ' -', 'Bonus -'
 |  ([ ]{digiwords}$)               # might not be delimited if at the end, '... Bonus'
)
\s*  # all succeeding space
    """,
    re.I | re.VERBOSE,
)


@dataclass
class Remix:
    PATTERN = re.compile(rf" *[\[(] *{REMIX.pattern}[])]", re.I)

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

    name: str = ""
    ft: str = ""
    catalognum: Optional[str] = None
    ft_artist: str = ""
    remix: Optional[Remix] = None

    digi_only: bool = False
    track_alt: Optional[str] = None

    @staticmethod
    def clean_digi_name(name: str) -> Tuple[str, bool]:
        """Clean the track title from digi-only artifacts.

        Return the clean name, and whether this track is digi-only.
        """
        clean_name = DIGI_ONLY_PATTERN.sub("", name)
        return clean_name, clean_name != name

    @staticmethod
    def split_ft(value: str) -> Tuple[str, str, str]:
        """Return ft artist, full ft string, and the value without the ft string."""
        if m := PATTERNS["ft"].search(value):
            grp = m.groupdict()
            return grp["ft_artist"], grp["ft"], value.replace(m.group(), "")

        return "", "", value

    @classmethod
    def get_featuring_artist(cls, name: str, artist: str) -> Dict[str, str]:
        """Find featuring artist in the track name.

        If the found artist is contained within the remixer, do not do anything.
        If the found artist is among the main artists, remove it from the name but
        do not consider it as a featuring artist.
        Otherwise, strip brackets and spaces and save it in the 'ft' field.
        """
        ft_artist, ft, name = cls.split_ft(name)

        if not ft_artist:
            ft_artist, ft, artist = cls.split_ft(artist)

        return {"name": name, "json_artist": artist, "ft": ft, "ft_artist": ft_artist}

    @classmethod
    def parse_name(cls, name: str, artist: str, index: Optional[int]) -> JSONDict:
        result: JSONDict = {}
        artist, artist_digi_only = cls.clean_digi_name(artist)
        name, name_digi_only = cls.clean_digi_name(name)
        result["digi_only"] = name_digi_only or artist_digi_only

        if artist:
            artist = Helpers.clean_name(artist)
        name = Helpers.clean_name(name).strip().lstrip("-")

        # find the track_alt and remove it from the name
        m = PATTERNS["track_alt"].search(name)
        if m:
            result["track_alt"] = m.group(1).replace(".", "").upper()
            name = name.replace(m.group(), "")

        # check whether track name contains the catalog number within parens
        # or square brackets
        # see https://objection999x.bandcamp.com/album/eruption-va-obj012
        m = CATNUM_PAT["delimited"].search(name)
        if m:
            result["catalognum"] = m.group(1)
            name = name.replace(m.group(), "").strip()

        # Remove leading index
        if index:
            name = re.sub(rf"^0*{index}(?!\W\d)\W+", "", name)

        # find the remixer and remove it from the name
        remix = Remix.from_name(name)
        if remix:
            result["remix"] = remix
            name = name.replace(remix.delimited, "").rstrip()

        return {**result, **cls.get_featuring_artist(name, artist)}

    @classmethod
    def make(cls, json: JSONDict, name: str) -> "Track":
        try:
            artist = json["inAlbum"]["byArtist"]["name"]
        except KeyError:
            artist = json.get("byArtist", {}).get("name", "")

        index = json.get("position")
        data = {
            "json_item": json,
            "track_id": json["@id"],
            "index": index,
            **cls.parse_name(name, artist, index),
        }
        return cls(**data)

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
            text: str = self.json_item["recordingOf"]["lyrics"]["text"]
        except KeyError:
            return ""
        else:
            return text.replace("\r", "")

    @cached_property
    def full_name(self) -> str:
        name = self.name
        if self.json_artist and " - " not in name:
            name = f"{self.json_artist} - {name}"
        return name.strip()

    @cached_property
    def title_without_remix(self) -> str:
        """Split the track name, deduce the title and return it.

        The extra complexity here is to ensure that it does not cut off a title
        that ends with ' - -', like in '(DJ) NICK JERSEY - 202memo - - -'.
        """
        parts = re.split(r" - (?![^\[(]+[])])", self.full_name)
        if len(parts) == 1:
            parts = self.full_name.split(" - ")
        title_without_remix = parts[-1]
        for idx, maybe in enumerate(reversed(parts)):
            if not maybe.strip(" -"):
                title_without_remix = " - ".join(parts[-idx - 2 :])
                break
        return title_without_remix

    @cached_property
    def title(self) -> str:
        """Return the main title with the full remixer part appended to it."""
        if self.remix:
            return f"{self.title_without_remix} {self.remix.delimited}"
        return self.title_without_remix

    @cached_property
    def artist(self) -> str:
        """Return name without the title and the remixer."""
        title_start_idx = self.full_name.rfind(self.title_without_remix)
        artist = Remix.PATTERN.sub("", self.full_name[:title_start_idx].strip(", -"))
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
            "artist": (
                f"{self.artist} {self.ft}"
                if self.ft_artist not in self.artist + self.title
                else self.artist
            ),
            "title": self.title,
            "length": self.duration,
            "track_alt": self.track_alt,
            "lyrics": self.lyrics,
            "catalognum": self.catalognum or None,
        }
