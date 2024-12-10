"""Module with a Helpers class that contains various static, independent functions."""

from __future__ import annotations

import re
from functools import cache, partial
from itertools import chain
from operator import contains
from re import Match, Pattern
from typing import TYPE_CHECKING, Any, Generic, NamedTuple, TypeVar

from beets import __version__ as beets_version
from packaging.version import Version
from typing_extensions import TypeAlias

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

J = TypeVar("J", bound=JSONDict)
T = TypeVar("T")


class cached_classproperty(Generic[T]):
    def __init__(self, getter: Callable[..., T]) -> None:
        self.getter = getter
        self.cache: dict[type[object], T] = {}

    def __get__(self, instance: object, owner: type[object]) -> T:
        if owner not in self.cache:
            self.cache[owner] = self.getter(owner)

        return self.cache[owner]


def cached_patternprop(
    pattern: str, flags: int = 0
) -> cached_classproperty[Pattern[str]]:
    """Pattern is compiled and cached the first time it is accessed."""
    return cached_classproperty(lambda _: re.compile(pattern, flags))


class MediaInfo(NamedTuple):
    album_id: str
    name: str
    disctitle: str
    description: str

    @classmethod
    def from_format(cls, format_: JSONDict) -> MediaInfo:
        release_format = format_.get("musicReleaseFormat")

        return cls(
            format_["@id"],
            FORMAT_TO_MEDIA[release_format or "DigitalFormat"],
            "" if release_format == "DigitalFormat" else format_["name"],
            (
                ""
                if release_format == "DigitalFormat"
                else format_.get("description") or ""
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


Replacement: TypeAlias = "tuple[Pattern[str], str | Callable[[Match[str]], str]]"


class Helpers:
    SPLIT_ARTISTS_PAT = cached_patternprop(r",(?= ?)| (?:[x+/-]|//|vs|and)[.]? ")
    SPLIT_ALL_ARTISTS_PAT = cached_patternprop(
        r",(?= ?)|& | (?:[X&x+/-]|//|vs|and)[.]? "
    )
    KEYWORD_SPLIT = cached_patternprop(r"[.] | #| - ")
    KEYWORD_SUBSPLIT = cached_patternprop(r"[ -]")
    FT_PAT = cached_patternprop(
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
    )

    @staticmethod
    @cache
    def get_replacements() -> list[Replacement]:
        rm_strings = [
            "limited edition",
            r"^EP -",
            r"\((digital )?album\)",
            r"\(single\)",
            r"\Wvinyl\W|vinyl-only|vinyl[^ ]*cd",
            "compiled by.*",
            "compilation: ",
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

        camelcase = re.compile(r"(?<=[a-z])(?=[A-Z])")

        def split_artist_title(m: Match[str]) -> str:
            """See for yourself.

            https://examine-archive.bandcamp.com/album/va-examine-archive-international-sampler-xmn01
            """
            artist, title = m.groups()
            artist = camelcase.sub(" ", artist)
            title = camelcase.sub(" ", title)

            return f"{artist} - {title}"

        # fmt: off
        return [
            (re.compile(rf"(([\[(])|(^| ))\*?({'|'.join(rm_strings)})(?(2)[])]|([- ]|$))", re.I), ""),  # noqa: E501
            (re.compile(r" -([^\s-])"), r" - \1"),                                          # hi -bye                   -> hi - bye  # noqa: E501
            (re.compile(r"([^\s-])- "), r"\1 - "),                                          # hi- bye                   -> hi - bye  # noqa: E501
            (re.compile(r"  +"), " "),                                                      # hi  bye                   -> hi bye  # noqa: E501
            (re.compile(r"(- )?\( *"), "("),                                                # hi - ( bye)               -> hi (bye)  # noqa: E501
            (re.compile(r" \)+|(\)+$)"), ")"),                                              # hi (bye ))                -> hi (bye)  # noqa: E501
            (re.compile(r"- Reworked"), "(Reworked)"),                                      # bye - Reworked            -> bye (Reworked)  # noqa: E501
            (re.compile(r"(\([^)]+mix)$", re.I), r"\1)"),                                  # bye - (Some Mix           -> bye - (Some Mix)  # noqa: E501
            (re.compile(r'(^|- )[“"]([^”"]+)[”"]( \(|$)'), r"\1\2\3"),                      # "bye" -> bye; hi - "bye"  -> hi - bye  # noqa: E501
            (re.compile(r"\((the )?(remixes)\)", re.I), r"\2"),                             # Album (Remixes)           -> Album Remixes  # noqa: E501
            (re.compile(r"^(\[[^]-]+\]) - (([^-]|-\w)+ - ([^-]|-\w)+)$"), r"\2 \1"),        # [Remixer] - hi - bye      -> hi - bye [Remixer]  # noqa: E501
            (re.compile(r"examine-.+CD\d+_([^_-]+)[_-](.*)"), split_artist_title),          # See https://examine-archive.bandcamp.com/album/va-examine-archive-international-sampler-xmn01  # noqa: E501
            (re.compile(r'"([^"]+)" by (.+)$'), r"\2 - \1"),                                # "bye" by hi               -> hi - bye  # noqa: E501
        ]
        # fmt: on

    @classmethod
    def remove_ft(cls, text: str) -> str:
        """Remove featuring artists from the text."""
        return cls.FT_PAT.sub("", text)

    @classmethod
    def split_artists(
        cls, artists: str | Iterable[str], force: bool = False
    ) -> list[str]:
        """Split artists taking into account delimiters such as ',', '+', 'x', 'X'.

        Note: featuring artists are removed since they are not main artists.
        """
        if not isinstance(artists, str):
            artists = ", ".join(artists)

        pat = cls.SPLIT_ALL_ARTISTS_PAT if force else cls.SPLIT_ARTISTS_PAT
        split = pat.split(cls.remove_ft(artists))
        split_artists = ordset(
            a for a in map(str.strip, split) if a not in {"", "more"}
        )
        if force:
            return list(split_artists)

        for artist in list(split_artists):
            # ' & ' or ' X ' may be part of single artist name, so we need to be careful
            # here. We check whether any of the split artists appears on their own and
            # only split then
            for subartists in (s for c in "X&" if len(s := artist.split(f" {c} ")) > 1):
                if any(a in split_artists for a in subartists):
                    split_artists.pop(artist)
                    split_artists |= ordset(subartists)
        return list(split_artists)

    @classmethod
    def clean_name(cls, name: str) -> str:
        """Both album and track names are cleaned using these patterns."""
        if name:
            for pat, repl in cls.get_replacements():
                name = pat.sub(repl, name).strip()
        return name

    @classmethod
    def get_genre(
        cls, keywords: Iterable[str], config: JSONDict, label: str
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
        always_include_pat = re.compile("|".join(config["always_include"]))

        def is_label_name(kw: str) -> bool:
            return kw.replace(" ", "") == label_name and not valid_mb_genre(kw)

        def is_included(kw: str) -> bool:
            return bool(always_include_pat.pattern and always_include_pat.search(kw))

        def valid_for_mode(kw: str) -> bool:
            if config["mode"] == "classical":
                return valid_mb_genre(kw)

            words = cls.KEYWORD_SUBSPLIT.split(kw)
            if config["mode"] == "progressive":
                return valid_mb_genre(kw) or all(map(valid_mb_genre, words))

            return valid_mb_genre(kw) or valid_mb_genre(words[-1])

        unique_genres: dict[str, None] = ordset([])
        # expand badly delimited keywords
        for kw in chain.from_iterable(map(cls.KEYWORD_SPLIT.split, keywords)):
            # remove full stops and hashes and ensure the expected form of 'and'
            kw_ = kw.strip("#").replace("&", "and").replace(".", "")
            if not is_label_name(kw_) and (is_included(kw_) or valid_for_mode(kw_)):
                unique_genres[kw_] = None

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
                and (obj["item_type"] != "p" or "bundle" not in obj["name"].lower())
            )

        valid_formats = filter(valid_format, map(Helpers.unpack_props, format_list))
        return list(map(MediaInfo.from_format, valid_formats))

    @staticmethod
    def check_list_fields(data: J) -> J:
        if "albumtypes" in data and not ALBUMTYPES_LIST_SUPPORT:
            data["albumtypes"] = "; ".join(data["albumtypes"])

        if not ARTIST_LIST_FIELDS_SUPPORT:
            fields = ["artists", "artists_ids", "artists_credit", "artists_sort"]
            for f in fields:
                data.pop(f)

        if "tracks" in data:
            data["tracks"] = [Helpers.check_list_fields(t) for t in data["tracks"]]

        return data
