"""Module with a single track parsing functionality."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from .catalognum import Catalognum
from .helpers import PATTERNS, Helpers, JSONDict

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
    PATTERN = re.compile(
        r"""
    (?P<start>^)?
    \ *\(?
    (?P<text>
      (?:
          (?P<b>\[)
        | (?P<p>\((?!.*\())
        | (?<!-)-\ (?!.*([([]|\ -\ ))
      )
      (?P<remixer>['"]?\b\w.*?|)\ *
      (?P<type>(re)?mix|edit|bootleg|(?<=\w\ )version|remastered)\b
      [^])]*
      (?(b)\])
      (?(p)\))
    )
    (?P<end>$)?
    """,
        re.IGNORECASE | re.VERBOSE,
    )

    full: str
    remixer: str
    text: str
    type: str
    start: bool
    end: bool

    @classmethod
    def from_name(cls, name: str) -> Remix | None:
        m = cls.PATTERN.search(name)
        if m:
            remix: dict[str, Any] = m.groupdict()
            remix["start"] = remix["start"] is not None
            remix["end"] = remix["end"] is not None
            remix["type"] = remix["type"].lower()
            remix.pop("b")
            remix.pop("p")
            return cls(**remix, full=m[0])
        return None

    @cached_property
    def valid(self) -> bool:
        return self.remixer.lower() != "original" and self.type != "remastered"

    @cached_property
    def artist(self) -> str | None:
        if self.valid and self.remixer.lower() != "extended" and self.type != "version":
            return self.remixer

        return None


@dataclass
class Track:
    DELIM_NOT_INSIDE_PARENS = re.compile(r"(?<!-) - (?!-|[^([]+\w[])])")
    json_item: JSONDict = field(default_factory=dict, repr=False)
    track_id: str = ""
    index: int | None = None
    medium_index: int | None = None
    json_artist: str = ""

    name: str = ""
    ft: str = ""
    catalognum: str | None = None
    ft_artist: str = ""
    remix: Remix | None = None

    digi_only: bool = False
    track_alt: str | None = None
    album_artist: str | None = None

    @staticmethod
    def clean_digi_name(name: str) -> tuple[str, bool]:
        """Clean the track title from digi-only artifacts.

        Return the clean name, and whether this track is digi-only.
        """
        clean_name = DIGI_ONLY_PATTERN.sub("", name)
        return clean_name, clean_name != name

    @staticmethod
    def split_ft(value: str) -> tuple[str, str, str]:
        """Return ft artist, full ft string, and the value without the ft string."""
        if m := PATTERNS["ft"].search(value):
            grp = m.groupdict()
            return grp["ft_artist"], grp["ft"], value.replace(m.group(), "")

        return "", "", value

    @classmethod
    def get_featuring_artist(cls, name: str, artist: str) -> dict[str, str]:
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
    def parse_name(cls, name: str, artist: str, index: int | None) -> JSONDict:
        result: JSONDict = {}
        artist, artist_digi_only = cls.clean_digi_name(artist)
        name, name_digi_only = cls.clean_digi_name(name)
        result["digi_only"] = name_digi_only or artist_digi_only

        if artist:
            artist = Helpers.clean_name(artist)
        name = Helpers.clean_name(name).strip()

        # find the track_alt and remove it from the name
        m = PATTERNS["track_alt"].search(name)
        if m:
            result["track_alt"] = m.group(1).replace(".", "").upper()
            name = name.replace(m.group(), "")

        # check whether track name contains the catalog number within parens
        # or square brackets
        # see https://objection999x.bandcamp.com/album/eruption-va-obj012
        m = Catalognum.delimited.search(name)
        if m:
            result["catalognum"] = m.group(1)
            name = name.replace(m.group(), "").strip()

        # Remove leading index
        if index:
            name = re.sub(rf"^0?{index}\W\W+", "", name)
            result["medium_index"] = index

        # find the remixer and remove it from the name
        remix = Remix.from_name(name)
        if remix:
            result["remix"] = remix
            if remix.start:
                name = name.removeprefix(remix.full).strip()
            elif remix.end:
                name = name.removesuffix(remix.full).strip()

        return {**result, **cls.get_featuring_artist(name, artist)}

    @classmethod
    def make(cls, json: JSONDict) -> Track:
        artist = json.get("byArtist", {}).get("name", "")
        index = json.get("position")
        data = {
            "json_item": json,
            "track_id": json["@id"],
            "index": index,
            "album_artist": json.get("album_artist"),
            **cls.parse_name(json["name"], artist, index),
        }
        return cls(**data)

    @cached_property
    def duration(self) -> int | None:
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
    def name_split(self) -> list[str]:
        name = self.name
        split = self.DELIM_NOT_INSIDE_PARENS.split(name.strip())
        if self.json_artist and " - " not in name:
            return [self.json_artist.strip(), *split]

        return split

    @cached_property
    def title_without_remix(self) -> str:
        return self.name_split[-1]

    @cached_property
    def title(self) -> str:
        """Return the main title with the full remixer part appended to it."""
        if self.remix and self.remix.text not in self.title_without_remix:
            return f"{self.title_without_remix} {self.remix.text}"
        return self.title_without_remix

    @cached_property
    def artist(self) -> str:
        """Return name without the title and the remixer."""
        if self.album_artist:
            return self.album_artist

        if not self.title_without_remix:
            return ""

        artist = " - ".join(self.name_split[:-1])
        artist = Remix.PATTERN.sub("", artist.strip(", -"))
        if self.remix and self.remix.artist:
            artist = artist.replace(self.remix.artist, "").strip(" ,")

        return ", ".join(map(str.strip, artist.strip(" -").split(",")))

    @property
    def artists(self) -> list[str]:
        return Helpers.split_artists(self.artist)

    @property
    def lead_artist(self) -> str:
        if artists := Helpers.split_artists(self.artist, force=True):
            return artists[0]

        return self.artist

    @property
    def info(self) -> JSONDict:
        artists = self.artists
        if self.ft_artist:
            artists.append(self.ft_artist)

        return {
            "index": self.index,
            "medium_index": self.medium_index,
            "medium": 1,
            "track_id": self.track_id,
            "artist": (
                f"{self.artist} {self.ft}"
                if self.ft_artist not in self.artist + self.title
                else self.artist
            ),
            "artists": artists,
            "title": self.title,
            "length": self.duration,
            "track_alt": self.track_alt,
            "lyrics": self.lyrics,
            "catalognum": self.catalognum or None,
        }
