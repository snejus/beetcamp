"""Module with a single track parsing functionality."""
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict


from .helpers import CATNUM_PAT, PATTERNS, Helpers, JSONDict, _remix_pat

if sys.version_info.minor > 7:
    from functools import cached_property  # pylint: disable=ungrouped-imports
else:
    from cached_property import cached_property  # type: ignore # pylint: disable=import-error # noqa

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
(\s|[^()\w])*  # preceding space or anything that is not a parens or an alphabetical char
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
ELP_ALBUM_PAT = re.compile(r"[- ]*\[([^\]]+ [EL]P)\]+")  # Title [Some Album EP]


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
    main_artist: str = ""

    name: str = ""
    ft_artist: str = ""
    ft_string: str = ""
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
            artist = json.get("byArtist", {}).get("name", "")

        catalognum = json.get("catalognum")
        index = json.get("position")
        data = {
            "json_item": json,
            "track_id": json["@id"],
            "index": index,
            "catalognum": catalognum,
            **cls.parse_name(json["name"], artist, delim, label, catalognum, index),
        }
        return cls(**data)

    @staticmethod
    def clean_digi_name(name: str) -> Tuple[str, bool]:
        """Clean the track title from digi-only artifacts.

        Return the clean name, and whether this track is digi-only.
        """
        clean_name = DIGI_ONLY_PATTERN.sub("", name)
        return clean_name, clean_name != name

    @staticmethod
    def get_ft_parts(value: str) -> Tuple[str, str, str]:
        """Return ft artist, full ft string without brackets, and 'value' without the ft artist."""
        m = PATTERNS["ft"].search(value)
        if not m:
            return "", "", ""

        grp = m.groupdict()
        return grp["artist"], grp["without_brackets"], m.group()

    @classmethod
    def get_featuring_artist(cls, name: str, artist: str) -> Dict[str, str]:
        """Find featuring artist in the track name.

        If the found artist is contained within the remixer, do not do anything.
        If the found artist is among the main artists, remove it from the name but
        do not consider it as a featuring artist.
        Otherwise, strip brackets and spaces and save it in the 'ft' field.
        """
        ft_artist_in_name, name_ft_string, full_name_ft = cls.get_ft_parts(name)
        ft_artist_in_artist, artist_ft_string, full_artist_ft = cls.get_ft_parts(artist)
        name = name.replace(full_name_ft, "")
        artist = artist.replace(full_artist_ft, "")

        return {
            "name": name,
            "main_artist": artist,
            "ft_string": name_ft_string or artist_ft_string,
            "ft_artist": ft_artist_in_name or ft_artist_in_artist,
        }

    @classmethod
    def parse_name(
        cls,
        name: str,
        artist: str,
        delim: Optional[str] = None,
        label: Optional[str] = None,
        catalognum: Optional[str] = None,
        index: Optional[int] = None,
    ) -> JSONDict:
        result: JSONDict = {}
        if delim:
            name = name.replace(f" {delim} ", " - ")

        # remove label from the end of the track name
        # see https://gutterfunkuk.bandcamp.com/album/gutterfunk-all-subject-to-vibes-various-artists-lp  # noqa
        if label and name.endswith(label):
            name = name.replace(label, "").strip(" -")

        artist, artist_digi_only = cls.clean_digi_name(artist)
        name, name_digi_only = cls.clean_digi_name(name)
        result["digi_only"] = name_digi_only or artist_digi_only
        artist = Helpers.clean_name(artist) if artist else ""

        name = Helpers.clean_name(name).strip().lstrip("-")

        m = PATTERNS["track_alt"].search(name)
        if m:
            result["track_alt"] = m.group(1).replace(".", "").upper()
            name = name.replace(m.group(), "")

        if not catalognum:
            # check whether track name contains the catalog number within parens
            # or square brackets
            # see https://objection999x.bandcamp.com/album/eruption-va-obj012
            m = CATNUM_PAT["delimited"].search(name)
            if m:
                result["catalognum"] = m.group(1)
                name = name.replace(m.group(), "").strip()

        # Remove leading index
        name = re.sub(rf"^0*{index or '[0-9]+'}(?!\W\d)\W+", "", name)

        remix = Remix.from_name(name)
        if remix:
            result["remix"] = remix
            name = name.replace(remix.delimited, "").rstrip()

        for m in ELP_ALBUM_PAT.finditer(name):
            result["album"] = m.group(1).replace('"', "")
            name = name.replace(m.group(), "")

        return {**result, **cls.get_featuring_artist(name, artist)}

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
        if self.main_artist and " - " not in name:
            name = f"{self.main_artist} - {name}"
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
        """Take the name, remove the title, ensure it does not duplicate any remixers
        and return the resulting artist.
        """
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
                self.artist
                + (f" {self.ft_string}" if self.ft_artist not in self.artist else "")
            ),
            "title": self.title,
            "length": self.duration,
            "track_alt": self.track_alt,
            "lyrics": self.lyrics,
            "catalognum": self.catalognum or None,
        }
