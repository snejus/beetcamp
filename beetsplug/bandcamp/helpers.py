"""Module with a Helpers class that contains various static, independent functions."""

from __future__ import annotations

import re
from functools import partial
from itertools import chain
from operator import contains
from re import Match, Pattern
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar

from beets import __version__ as beets_version
from packaging.version import Version

from .genres_lookup import GENRES

ordset = dict.fromkeys

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

BEETS_VERSION = Version(beets_version)
ALBUMTYPES_LIST_SUPPORT = BEETS_VERSION >= Version("1.6.0")
ARTIST_LIST_FIELDS_SUPPORT = BEETS_VERSION >= Version("2.0.0")

JSONDict = dict[str, Any]
DIGI_MEDIA = "Digital Media"
USB_TYPE_ID = 5
FORMAT_TO_MEDIA = {
    "VinylFormat": "Vinyl",
    "CDFormat": "CD",
    "CassetteFormat": "Cassette",
    "DigitalFormat": DIGI_MEDIA,
    "DVDFormat": "DVD",
    "USB Flash Drive": DIGI_MEDIA,
}

T = TypeVar("T", bound=JSONDict)


class MediaInfo(NamedTuple):
    album_id: str
    name: str
    disctitle: str
    description: str

    @classmethod
    def from_format(cls, _format: JSONDict) -> MediaInfo:
        release_format = _format.get("musicReleaseFormat")

        return cls(
            _format["@id"],
            FORMAT_TO_MEDIA[release_format or "DigitalFormat"],
            "" if release_format == "DigitalFormat" else _format["name"],
            (
                ""
                if release_format == "DigitalFormat"
                else _format.get("description") or ""
            ),
        )

    @property
    def medium_count(self) -> int:
        if self.name == "Vinyl" and (
            m := re.search(
                r"[1-5](?= ?(xLP|LP|x))|single|double|triple", self.disctitle, re.I
            )
        ):
            count = m.group()
            if count.isdigit():
                return int(count)

            return {"single": 1, "double": 2, "triple": 3}[count.lower()]

        return 1


PATTERNS: dict[str, Pattern[str]] = {
    "split_artists": re.compile(r", - |, ?| (?:[x+/-]|//|vs|and)[.]? "),
    "meta": re.compile(r'.*"@id".*'),
    "ft": re.compile(
        r"""
        [ ]*                            # all preceding space
        ((?P<br>[([{])|\b)              # bracket or word boundary
        (?P<ft>
            (ft|feat|featuring|(?<=\()with|w/(?![ ]you))[. ]+ # any ft variation
            (?P<ft_artist>.+?)
            (?<!mix)                    # does not end with "mix"
            (\b|['"])                   # ends with a word boundary or quote
        )
        (?(br)                          # if started with a bracket
              [])}]                     # must end with a closing bracket
            | (?=\ -\ |\ *[][)(/]|$)    # otherwise ends with of these combinations
        )
    """,
        re.I | re.VERBOSE,
    ),
    "track_alt": re.compile(
        r"""
        (?:(?<=^)|(?<=-\ ))             # beginning of the line or after the separator
        (
            (?:[A-J]{1,3}[12]?\.?\d)    # A1, B2, E4, A1.1 etc.
          | (?:[AB]+(?!\ \()(?=\W{2}\b))# A, AA BB
        )
        (?:[/.:)_\s-]+)                 # consume the non-word chars for removal
    """,
        re.M | re.VERBOSE,
    ),
}
rm_strings = [
    "limited edition",
    r"^EP -",
    r"\((digital )?album\)",
    r"\(single\)",
    r"\Wvinyl\W|vinyl-only|vinyl[^ ]*cd",
    "compiled by.*",
    r"[\[(](presented|selected) by.*",
    r"[ |-]*free download(?! \w)",
    r"[([][^])]*free\b(?!.*mix)[^])]*[])]",
    r"[([][^])]*preview[])]",
    r"(\W|\W )bonus( \w+)*",
    "Various -",
    "split w",
    r"CD ?\d+",
    "Name Your Price:",
    "just out!",
    "- album",
]

REMIX = re.compile(
    r"(?P<remix>\W*(?P<text>((?P<remixer>\b\w[^])]+) )?\b((re)?mix|edit|bootleg)\b)[^])]*)",  # noqa: E501
    re.I,
)
CAMELCASE = re.compile(r"(?<=[a-z])(?=[A-Z])")


def split_artist_title(m: Match[str]) -> str:
    """See for yourself.

    https://examine-archive.bandcamp.com/album/va-examine-archive-international-sampler-xmn01
    """
    artist, title = m.groups()
    artist = CAMELCASE.sub(" ", artist)
    title = CAMELCASE.sub(" ", title)

    return f"{artist} - {title}"


# fmt: off
CLEAN_PATTERNS: list[tuple[Pattern[str], str | Callable[[Match[str]], str]]] = [
    (re.compile(rf"(([\[(])|(^| ))\*?({'|'.join(rm_strings)})(?(2)[])]|([- ]|$))", re.I), ""),  # noqa
    (re.compile(r" -([^\s-])"), r" - \1"),                                          # hi -bye                   -> hi - bye  # noqa
    (re.compile(r"([^\s-])- "), r"\1 - "),                                          # hi- bye                   -> hi - bye  # noqa
    (re.compile(r"  +"), " "),                                                      # hi  bye                   -> hi bye  # noqa
    (re.compile(r"(- )?\( *"), "("),                                                # hi - ( bye)               -> hi (bye)  # noqa
    (re.compile(r" \)+|(\)+$)"), ")"),                                              # hi (bye ))                -> hi (bye)  # noqa
    (re.compile(r"- Reworked"), "(Reworked)"),                                      # bye - Reworked            -> bye (Reworked)  # noqa
    (re.compile(rf"(?<= - )([^()]+?) - ({REMIX.pattern})$", re.I), r"\1 (\2)"),     # - bye - Some Mix          -> - bye (Some Mix)  # noqa
    (re.compile(rf"(\({REMIX.pattern})$", re.I), r"\1)"),                           # bye - (Some Mix           -> bye - (Some Mix)  # noqa
    (re.compile(rf"- *({REMIX.pattern})$", re.I), r"(\1)"),                         # bye - Some Mix            -> bye (Some Mix)  # noqa
    (re.compile(r'(^|- )[“"]([^”"]+)[”"]( \(|$)'), r"\1\2\3"),                      # "bye" -> bye; hi - "bye"  -> hi - bye  # noqa
    (re.compile(r"\((the )?(remixes)\)", re.I), r"\2"),                             # Album (Remixes)           -> Album Remixes  # noqa
    (re.compile(r"^(\[[^]-]+\]) - (([^-]|-\w)+ - ([^-]|-\w)+)$"), r"\2 \1"),        # [Remixer] - hi - bye      -> hi - bye [Remixer]  # noqa
    (re.compile(r"examine-.+CD\d+_([^_-]+)[_-](.*)"), split_artist_title),          # See https://examine-archive.bandcamp.com/album/va-examine-archive-international-sampler-xmn01  # noqa
    (re.compile(r'"([^"]+)" by (.+)$'), r"\2 - \1"),                                # "bye" by hi               -> hi - bye  # noqa: E501
]
# fmt: on


class Helpers:
    @staticmethod
    def remove_ft(text: str) -> str:
        """Remove featuring artists from the text."""
        return PATTERNS["ft"].sub("", text)

    @classmethod
    def split_artists(
        cls, artists: str | Iterable[str], force: bool = False
    ) -> list[str]:
        """Split artists taking into account delimiters such as ',', '+', 'x', 'X'.

        Note: featuring artists are removed since they are not main artists.
        """
        if not isinstance(artists, str):
            artists = ", ".join(artists)

        split = PATTERNS["split_artists"].split(cls.remove_ft(artists))
        split_artists = ordset(
            a for a in map(str.strip, split) if a not in {"", "more"}
        )

        for artist in list(split_artists):
            # ' & ' or ' X ' may be part of single artist name, so we need to be careful
            # here. We check whether any of the split artists appears on their own and
            # only split then
            for subartists in (s for c in "X&" if len(s := artist.split(f" {c} ")) > 1):
                if force or any(a in split_artists for a in subartists):
                    split_artists.pop(artist)
                    split_artists |= ordset(subartists)
        return list(split_artists)

    @staticmethod
    def clean_name(name: str) -> str:
        """Both album and track names are cleaned using these patterns."""
        if name:
            for pat, repl in CLEAN_PATTERNS:
                name = pat.sub(repl, name).strip()
        return name

    @staticmethod
    def get_genre(
        keywords: Iterable[str], config: JSONDict, label: str
    ) -> Iterable[str]:
        """Return a comma-delimited list of valid genres, using MB genres for reference.

        1. Exclude keywords that are label names, unless they are a valid MB genre

        2. Verify each keyword's (potential genre) validity w.r.t. the configured `mode`
          * classical: valid only if the _entire keyword_ matches a MB genre in the list
          * progressive: either above or if each of the words matches MB genre - since
            it is effectively a subgenre.
          * psychedelic: one of the above or if the last word is a valid MB genre.
            This allows to be flexible regarding the variety of potential genres while
            keeping away from spammy ones.

        3. Once we have the list of keywords that coming out of the mode filters,
           an additional filter is executed:
           * if a keyword is _part of another keyword_ (genre within a sub-genre),
             we keep the more specific genre, for example
             >>> get_genre(["house", "garage house", "glitch"], "classical")
             ["garage house", "glitch"]

             "garage house" is preferred over "house".
        """
        valid_mb_genre = partial(contains, GENRES)
        label_name = label.lower().replace(" ", "")

        def is_label_name(kw: str) -> bool:
            return kw.replace(" ", "") == label_name and not valid_mb_genre(kw)

        def is_included(kw: str) -> bool:
            return any(re.search(x, kw) for x in config["always_include"])

        def valid_for_mode(kw: str) -> bool:
            if config["mode"] == "classical":
                return valid_mb_genre(kw)

            words = map(str.strip, re.split("[ -]", kw))
            if config["mode"] == "progressive":
                return valid_mb_genre(kw) or all(map(valid_mb_genre, words))

            return valid_mb_genre(kw) or valid_mb_genre(list(words)[-1])

        unique_genres: dict[str, None] = ordset([])
        # expand badly delimited keywords
        split_kw = partial(re.split, r"[.] | #| - ")
        for kw in chain.from_iterable(map(split_kw, keywords)):
            # remove full stops and hashes and ensure the expected form of 'and'
            _kw = re.sub("[.#]", "", str(kw)).replace("&", "and")
            if not is_label_name(_kw) and (is_included(_kw) or valid_for_mode(_kw)):
                unique_genres[_kw] = None

        def within_another_genre(genre: str) -> bool:
            """Check if this genre is part of another genre.

            Remove spaces and dashes from the rest of genres and check if any of them
            contain the given genre.

            This is so that 'dark folk' is kept while 'darkfolk' is removed, and not
            the other way around.
            """
            others = ordset(g for g in unique_genres if g not in genre)
            others |= ordset(x.replace(" ", "").replace("-", "") for x in others)
            return any(genre in x for x in others)

        return (g for g in unique_genres if not within_another_genre(g))

    @staticmethod
    def unpack_props(obj: JSONDict) -> JSONDict:
        """Add all 'additionalProperty'-ies to the parent dictionary."""
        for prop in obj.get("additionalProperty") or []:
            obj[prop["name"]] = prop["value"]
        return obj

    @staticmethod
    def get_media_formats(format_list: list[JSONDict]) -> list[MediaInfo]:
        """Return filtered Bandcamp media formats as a list of MediaInfo objects.

        Formats are filtered using the following fields,
        type_id item_type  type_name          musicReleaseFormat
                a          Digital            DigitalFormat   # digital album
                b          Digital            DigitalFormat   # discography
                t          Digital            DigitalFormat   # digital track
                i          Digital            DigitalFormat   # subscription
        0       p          Other
        1       p          Compact Disc (CD)  CDFormat
        2       p          Vinyl LP           VinylFormat
        3       p          Cassette           CassetteFormat
        4       p          DVD                DVDFormat
        5       p          USB Flash Drive
        10      p          Poster/Print
        11      p          T-Shirt/Apparel
        15      p          2 x Vinyl LP       VinylFormat
        16      p          7" Vinyl           VinylFormat
        17      p          Vinyl Box Set      VinylFormat
        18      p          Other Vinyl        VinylFormat
        19      p          T-Shirt/Shirt
        20      p          Sweater/Hoodie
        """

        def valid_format(obj: JSONDict) -> bool:
            return (
                {"name", "item_type"} < set(obj)
                # not a discography
                and obj["item_type"] != "b"
                # not a subscription
                and obj["item_type"] != "i"
                # musicReleaseFormat format is given or it is a USB
                and ("musicReleaseFormat" in obj or obj["type_id"] == USB_TYPE_ID)
                # it is not a vinyl bundle
                and not (obj["item_type"] == "p" and "bundle" in obj["name"].lower())
            )

        valid_formats = filter(valid_format, map(Helpers.unpack_props, format_list))
        return list(map(MediaInfo.from_format, valid_formats))

    @staticmethod
    def check_list_fields(data: T) -> T:
        if "albumtypes" in data and not ALBUMTYPES_LIST_SUPPORT:
            data["albumtypes"] = "; ".join(data["albumtypes"])

        if not ARTIST_LIST_FIELDS_SUPPORT:
            fields = ["artists", "artists_ids", "artists_credit", "artists_sort"]
            for f in fields:
                data.pop(f)

        if "tracks" in data:
            data["tracks"] = [Helpers.check_list_fields(t) for t in data["tracks"]]

        return data
