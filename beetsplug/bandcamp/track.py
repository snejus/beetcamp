"""Module with a single track parsing functionality."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from .catalognum import Catalognum
from .helpers import Helpers, JSONDict, cached_patternprop

digiwords = r"""
    # must contain at least one of
    ([ -]?  # delimiter
        (bandcamp|digi(tal)?|exclusive|bonus|bns|unreleased)
    )+
    # and may be followed by
    (\W(track|only|tune))*
    """


@dataclass
class Remix:
    PATTERN = cached_patternprop(
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
      (?P<type>(re)?mix|rmx|edit|bootleg|(?<=\w\ )version|remastered)\b
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
        if m := cls.PATTERN.search(name):
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
    DIGI_ONLY_PAT = cached_patternprop(
        rf"""
    (\s|[^][()\w])*  # space or anything that is not a parens or an alphabetical char
    (
          (^{digiwords}[.:\d\s]+\s)     # begins with 'Bonus.', 'Bonus 1.' or 'Bonus :'
     | [\[(]{digiwords}[\])]\W*         # delimited by brackets, '[Bonus]', '(Bonus) -'
     |   [*]{digiwords}[*]?             # delimited by asterisks, '*Bonus', '*Bonus*'
     |      {digiwords}[ ]-             # followed by ' -', 'Bonus -'
     |  ([ ]{digiwords}$)               # might not be delimited at the end, '... Bonus'
    )
    \s*  # all succeeding space
        """,
        re.I | re.VERBOSE,
    )
    DELIM_NOT_INSIDE_PARENS = cached_patternprop(
        r"(?<!-)(?<!^live)(?<!sample\ pack) - (?!-|[^([]+\w[])])", re.I
    )
    TRACK_ALT_PAT = cached_patternprop(
        r"""
        (?:(?<=^)|(?<=-\ ))             # beginning of the line or after the separator
        (
            (?:[A-J]{1,3}[12]?\.?\d)    # A1, B2, E4, A1.1 etc.
          | (?:[AB]+(?!\ \()(?=\W{2}\b))# A, AA BB
        )
        (?:[/.:)_\s-]+)                 # consume the non-word chars for removal
        """,
        re.M | re.VERBOSE,
    )
    NUMBER_PAT = cached_patternprop(r"\d+")

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

    @classmethod
    def clean_digi_name(cls, name: str) -> tuple[str, bool]:
        """Clean the track title from digi-only artifacts.

        Return the clean name, and whether this track is digi-only.
        """
        clean_name = cls.DIGI_ONLY_PAT.sub("", name)
        return clean_name, clean_name != name

    @staticmethod
    def split_ft(value: str) -> tuple[str, str, str]:
        """Return ft artist, full ft string, and the value without the ft string."""
        if m := Helpers.FT_PAT.search(value):
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

        if m := cls.TRACK_ALT_PAT.search(name):
            result["track_alt"] = m.group(1).replace(".", "").upper()
            name = name.replace(m.group(), "")

        if m := Catalognum.delimited.search(name):
            result["catalognum"] = m.group(1)
            name = name.replace(m.group(), "").strip()

        # Remove leading index
        if index:
            name = re.sub(rf"^0?{index}\W\W+", "", name)
            result["medium_index"] = index

        if remix := Remix.from_name(name):
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
            h, m, s = map(int, self.NUMBER_PAT.findall(self.json_item["duration"]))
        except KeyError:
            return None

        return h * 3600 + m * 60 + s

    @cached_property
    def lyrics(self) -> str:
        try:
            text: str = self.json_item["recordingOf"]["lyrics"]["text"]
        except KeyError:
            return ""

        return text.replace("\r", "")

    @cached_property
    def name_split(self) -> list[str]:
        name = self.name
        if (a := self.json_artist) and name.lower().startswith(
            artist_start := f"{a.lower()} - "
        ):
            return [name[len(artist_start) :]]

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

    @staticmethod
    def clean_duplicate_artists(artist: str, remix_text: str) -> str:
        """Remove the artist from the artist field if it's already in the remix text."""
        for subartist in Helpers.split_artists(artist, force=True):
            if subartist.lower() in remix_text:
                artist = re.sub(
                    rf"(and|x|\W*)+\b{re.escape(subartist)}", "", artist, flags=re.I
                )
        return artist

    @cached_property
    def artist(self) -> str:
        """Deduce the artist from the track name."""
        if self.album_artist:
            return self.album_artist

        if not self.title_without_remix:
            return ""

        if self.json_artist and len(self.name_split) == 1:
            return self.json_artist

        artist = " - ".join(self.name_split[:-1])
        initial_artist = artist
        artist = Remix.PATTERN.sub("", artist.strip(", -"))
        if artist and self.remix and self.remix.artist:
            artist = self.clean_duplicate_artists(artist, self.remix.text.lower())

        # reset the artist back to the original for singletons, if it's gone
        if not artist and not self.index:
            artist = initial_artist

        return ", ".join(map(str.strip, artist.strip(", -").split(",")))

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
        if ft := self.ft_artist:
            artists.append(ft)
        artists = Helpers.split_artists(artists, force=True)

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
