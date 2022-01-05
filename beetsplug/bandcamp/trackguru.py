import operator as op
import re
import typing as t
from math import floor

from cached_property import cached_property

JSONDict = t.Dict[str, t.Any]

TRACK_ALT = re.compile(r"([ABCDEFGH]{1,3}[0-9])(\.|.?-\s|\s)")
DIGITAL = [
    re.compile(r"^(DIGI(TAL)? ?[\d.]+|Bonus\W{2,})\W*"),
    re.compile(
        r"(?i:[^\w\)]+(bandcamp[^-]+|digi(tal)?)(\W*(\W+|only|bonus|exclusive)\W*$))"
    ),
]
REMIX_OR_FT = re.compile(r"\s(?i:[\[\(].*(mix|edit)|f(ea)?t\.).*")


class Trackguru:
    @staticmethod
    def clean_digital_only_track(name: str) -> t.Tuple[str, bool]:
        """Return cleaned title and whether this track is digital-only."""
        clean_name = name
        for pat in DIGITAL:
            clean_name = pat.sub("", clean_name)
        if clean_name != name:
            return clean_name, True
        return clean_name, False

    @staticmethod
    def get_track_artist(parsed_artist, raw_track, albumartist):
        # type: (t.Optional[str], JSONDict, str) -> str
        """Return the first of the following options, if found:
        1. Parsed artist from the track title
        2. Artist specified by Bandcamp (official)
        3. Albumartist (worst case scenario)
        """
        official_artist = raw_track.get("byArtist", {}).get("name", "")
        return parsed_artist or official_artist or albumartist

    @staticmethod
    def get_duration(source: JSONDict) -> int:
        prop = [
            x.get("value") or 0
            for x in source.get("additionalProperty", [])
            if x.get("name") == "duration_secs"
        ]
        if len(prop) == 1:
            return floor(prop[0])
        return 0

    @staticmethod
    def parse_track_name(name: str, catalognum: str = "") -> t.Dict[str, t.Optional[str]]:
        track: t.Dict[str, t.Optional[str]] = {
            a: "" for a in ["track_alt", "artist", "title", "main_title"]
        }

        # remove catalognum if given
        if catalognum:
            name = name.replace(catalognum, "").strip(", ")

        # remove leading numerical index if found
        name = re.sub(r"^[01]?[0-9][. ]\s?(?=[A-Z])", "", name).strip(", ")

        # match track alt and remove it from the name
        match = TRACK_ALT.match(name)
        if match:
            track_alt = match.expand(r"\1")
            track["track_alt"] = track_alt
            name = name.replace(track_alt, "")

        # do not strip a period from the end since it could end with an abbrev
        name = name.lstrip(".")
        # in most cases that's the delimiter between the artist and the title
        parts = re.split(r"\s?-\s|\s-\s?", name.strip(",- "))

        # title is always given
        track["title"] = parts.pop(-1)
        track["main_title"] = REMIX_OR_FT.sub("", track.get("title") or "")

        # whatever is left must be the artist
        if len(parts):
            track["artist"] = ", ".join(parts).strip(", ")
        return track

    @cached_property
    def tracks(self) -> t.List[JSONDict]:
        """Parse relevant details from the tracks' JSON."""
        try:
            raw_tracks = self.meta["track"].get("itemListElement", [])
        except KeyError:
            raw_tracks = [{"item": self.meta}]

        albumartist = self.bandcamp_albumartist
        catalognum = self.catalognum
        tracks = []
        for raw_track in raw_tracks:
            raw_item = raw_track["item"]
            index = raw_track.get("position") or 1
            name, digital_only = self.clean_digital_only_track(raw_item["name"])
            name = self.clean_name(name, *filter(op.truth, [self.catalognum, self.label]))
            track = dict(
                digital_only=digital_only,
                index=index,
                medium_index=index,
                track_id=raw_item.get("@id"),
                length=self.get_duration(raw_item) or None,
                **self.parse_track_name(name, catalognum),
            )
            track["artist"] = self.get_track_artist(
                track["artist"], raw_item, albumartist
            )
            lyrics = raw_item.get("recordingOf", {}).get("lyrics", {}).get("text")
            if lyrics:
                track["lyrics"] = lyrics.replace("\r", "")
            else:
                track["lyrics"] = None

            tracks.append(track)

        return tracks
