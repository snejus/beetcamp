"""Module with a Helpers class that contains various static, independent functions."""

import re
from functools import lru_cache, partial
from itertools import chain, starmap
from operator import contains
from typing import Any, Dict, Iterable, List, NamedTuple, Pattern

from beets.autotag.hooks import AlbumInfo
from ordered_set import OrderedSet as ordset

from .genres_lookup import GENRES

JSONDict = Dict[str, Any]
DIGI_MEDIA = "Digital Media"
FORMAT_TO_MEDIA = {
    "VinylFormat": "Vinyl",
    "CDFormat": "CD",
    "CassetteFormat": "Cassette",
    "DigitalFormat": DIGI_MEDIA,
    "DVDFormat": "DVD",
    "USB Flash Drive": DIGI_MEDIA,
}


class MediaInfo(NamedTuple):
    album_id: str
    name: str
    title: str
    description: str


CATALOGNUM_CONSTRAINT = r"""(?<![]/@-])(\b
(?!\W|LC[ ]|VA[\d ]+|[EL]P[\W\d]|[^\n.]+[ ](?:20\d\d|VA[ \d]+)|(?i:vol|disc|number|rd-9))
{}
\b(?!["%]))"""
_cat_pat = CATALOGNUM_CONSTRAINT.format(
    r"""
(
      [A-Z][A-Z .]+\d{3}         # HANDS D300, CC ATOM 101
    | [A-Z-]{3,}\d+              # RIV4
    | [A-Z]{2,}[A-Z.$-]*\d{2,}   # HS11, USE202, HEY-101, LI$INGLE025
    | (?<!\w\W)[A-Z.]{2,}[ ]\d+  # OBS.CUR 9
    | [A-z]+-[A-z]+[ ]?\d+       # o-ton 119
    | [A-z]+[ ]?(?:[EL]P)\d+     # Dystopian LP01
    | \w+[A-z]0\d+               # 1ØPILLS018, fa036
    | [a-z]+(?:cd|lp|:)\d+       # ostgutlp45, reni:7
    | [A-z]+\d+-\d+              # P90-003
)
(?: # optionally followed by
      (?<=\d\d)-?[A-Z]+  # IBM001CD (needs at least two digits before the letter)
    | [.]\d+             # ISMVA002.1
)?
"""
)

LABEL_CATNUM = CATALOGNUM_CONSTRAINT.format(r"(?i:{}[ ]?[A-Z]*\d+[A-Z]*)")
CATNUM_PAT = {
    # preceded by some variation of 'Catalogue number:'
    "header": re.compile(r"^cat[\w .]+(?:number\b:?|:) ?(\w.+)$", re.I | re.M),
    # beginning or end of line
    "start_end": re.compile(rf"(^{_cat_pat}|{_cat_pat}$)", re.M | re.VERBOSE),
    # enclosed by parens or square brackets, but not ending with MIX
    "delimited": re.compile(rf"(?:[\[(])(?!.*MIX){_cat_pat}(?:[])]|$)", re.VERBOSE),
    # can possibly be followed up by a second catalogue number
    "anywhere": re.compile(rf"({_cat_pat}(\ [/-]\ {_cat_pat})?)", re.VERBOSE),
}

PATTERNS: Dict[str, Pattern[str]] = {
    "split_artists": re.compile(r", - |, | (?:[x+/-]|//|vs|and)[.]? "),
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
        r"^([A-J]{1,3}[12]?\.?\d|[AB]+(?=\W{2,}))(?:(?!-\w)[^\w(]|_)+", re.I + re.M
    ),
    "vinyl_name": re.compile(r"[1-5](?= ?(xLP|LP|x))|single|double|triple", re.I),
}
rm_strings = [
    "limited edition",
    r"^[EL]P( \d+)?",
    r"\((digital )?album\)",
    r"\(single\)",
    r"\Wvinyl\W|vinyl-only",
    "compiled by.*",
    r"[\[(]presented by.*",
    r"free download|\([^()]*\bfree(?!.*mix)[^()]*\)",
    r"(\W|\W )bonus( \w+)*",
    "Various -",
    r"CD ?\d+",
]

REMIX = re.compile(
    r"(?P<remix>((?P<remixer>[^])]+) )?\b((re)?mix|edit|bootleg)\b[^])]*)", re.I
)
CAMELCASE = re.compile(r"(?<=[a-z])(?=[A-Z])")


def split_artist_title(m: re.Match) -> str:
    """See for yourself.

    https://examine-archive.bandcamp.com/album/va-examine-archive-international-sampler-xmn01
    """
    artist, title = m.groups()
    artist = CAMELCASE.sub(" ", artist)
    title = CAMELCASE.sub(" ", title)

    return f"{artist} - {title}"


# fmt: off
CLEAN_PATTERNS = [
    (re.compile(rf"(([\[(])|(^| ))\*?({'|'.join(rm_strings)})(?(2)[])]|([- ]|$))", re.I), ""),       # noqa
    (re.compile(r" -(\S)"), r" - \1"),                    # hi -bye          -> hi - bye
    (re.compile(r"(\S)- "), r"\1 - "),                    # hi- bye          -> hi - bye
    (re.compile(r"  +"), " "),                            # hi  bye          -> hi bye
    (re.compile(r"(- )?\( *"), "("),                      # hi - ( bye)      -> hi (bye)
    (re.compile(r" \)+|(\)+$)"), ")"),                    # hi (bye ))       -> hi (bye)
    (re.compile(r"- Reworked"), "(Reworked)"),            # bye - Reworked   -> bye (Reworked)    # noqa
    (re.compile(rf"(\({REMIX.pattern})$", re.I), r"\1)"),    # bye - (Some Mix  -> bye - (Some Mix)  # noqa
    (re.compile(rf"- *({REMIX.pattern})$", re.I), r"(\1)"),  # bye - Some Mix   -> bye (Some Mix)    # noqa
    (re.compile(r'(^|- )[“"]([^”"]+)[”"]( \(|$)'), r"\1\2\3"),   # "bye" -> bye; hi - "bye" -> hi - bye  # noqa
    (re.compile(r"\((the )?(remixes)\)", re.I), r"\2"),   # Album (Remixes)  -> Album Remixes     # noqa
    (re.compile(r"examine-.+CD\d+_([^_-]+)[_-](.*)"), split_artist_title),  # See https://examine-archive.bandcamp.com/album/va-examine-archive-international-sampler-xmn01 # noqa
]
# fmt: on


class Helpers:
    @staticmethod
    def get_label(meta: JSONDict) -> str:
        try:
            item = meta.get("inAlbum", meta)["albumRelease"][0]["recordLabel"]
        except (KeyError, IndexError):
            item = meta["publisher"]
        return item.get("name") or ""

    @staticmethod
    def get_vinyl_count(name: str) -> int:
        conv = {"single": 1, "double": 2, "triple": 3}
        for m in PATTERNS["vinyl_name"].finditer(name):
            count = m.group()
            return int(count) if count.isdigit() else conv[count.lower()]
        return 1

    @staticmethod
    def split_artists(artists: Iterable[str]) -> List[str]:
        """Split artists taking into account delimiters such as ',', '+', 'x', 'X' etc.
        Note: featuring artists are removed since they are not main artists.
        """
        no_ft_artists = (PATTERNS["ft"].sub("", a) for a in artists)
        split = map(PATTERNS["split_artists"].split, ordset(no_ft_artists))
        split_artists = ordset(map(str.strip, chain(*split))) - {"", "more"}

        for artist in list(split_artists):
            # ' & ' or ' X ' may be part of single artist name, so we need to be careful
            # here. We check whether any of the split artists appears on their own and
            # only split then
            for char in "X&":
                subartists = artist.split(f" {char} ")
                if len(subartists) > 1 and any(s in split_artists for s in subartists):
                    split_artists.discard(artist)  # type: ignore[attr-defined]
                    split_artists.update(subartists)  # type: ignore[attr-defined]
        return list(split_artists)

    @staticmethod
    @lru_cache(maxsize=None)
    def parse_catalognum(
        album="", disctitle="", description="", label="", artistitles=""
    ):
        # type: (str, str, str, str, str) -> str
        """Try getting the catalog number looking at text from various fields."""
        cases = [
            (CATNUM_PAT["header"], description),
            (CATNUM_PAT["anywhere"], disctitle),
            (CATNUM_PAT["anywhere"], album),
            (CATNUM_PAT["start_end"], description),
            (CATNUM_PAT["anywhere"], description),
        ]
        if label:
            pat = re.compile(LABEL_CATNUM.format(re.escape(label)), re.VERBOSE)
            cases.append((pat, "\n".join((album, disctitle, description))))

        def find(pat: Pattern[str], string: str) -> str:
            """Return the match.

            It is legitimate if it is
            * not found in any of the track artists or titles
            * made of the label name when it has a space and is shorter than 6 chars
            """
            for m in pat.finditer(string):
                catnum = m.group(1).strip()
                if catnum.lower() not in artistitles:
                    if " " in catnum:
                        first = catnum.split()[0].lower()
                        if len(catnum) <= 5 and first not in label.lower():
                            continue
                    return catnum
            return ""

        try:
            return next(filter(None, starmap(find, cases)))
        except StopIteration:
            return ""

    @staticmethod
    def clean_name(name: str) -> str:
        """Both album and track names are cleaned using these patterns."""
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

        unique_genres: ordset[str] = ordset()
        # expand badly delimited keywords
        split_kw = partial(re.split, r"[.] | #| - ")
        for kw in chain.from_iterable(map(split_kw, keywords)):
            # remove full stops and hashes and ensure the expected form of 'and'
            _kw = re.sub("[.#]", "", str(kw)).replace("&", "and")
            if not is_label_name(_kw) and (is_included(_kw) or valid_for_mode(_kw)):
                unique_genres.add(_kw)

        def within_another_genre(genre: str) -> bool:
            """Check if this genre is part of another genre.

            Remove spaces and dashes from the rest of genres and check if any of them
            contain the given genre.

            This is so that 'dark folk' is kept while 'darkfolk' is removed, and not
            the other way around.
            """
            others = unique_genres - {genre}
            others |= {x.replace(" ", "").replace("-", "") for x in others}
            return any(genre in x for x in others)

        return (g for g in unique_genres if not within_another_genre(g))

    @staticmethod
    def unpack_props(obj: JSONDict) -> JSONDict:
        """Add all 'additionalProperty'-ies to the parent dictionary."""
        for prop in obj.get("additionalProperty") or []:
            obj[prop["name"]] = prop["value"]
        return obj

    @staticmethod
    def get_media_formats(format_list: List[JSONDict]) -> List[MediaInfo]:
        """Return filtered Bandcamp media formats as a list of MediaInfo objects.
        Formats are filtered using the following fields,

        type_id item_type  type_name          musicReleaseFormat
                a          Digital            DigitalFormat   # digital album
                b          Digital            DigitalFormat   # discography
                t          Digital            DigitalFormat   # digital track
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
                # musicReleaseFormat format is given or it is a USB
                and ("musicReleaseFormat" in obj or obj["type_id"] == 5)
                # it is not a vinyl bundle
                and not (obj["item_type"] == "p" and "bundle" in obj["name"].lower())
            )

        formats = []
        for _format in filter(valid_format, map(Helpers.unpack_props, format_list)):
            formats.append(
                MediaInfo(
                    _format["@id"],
                    FORMAT_TO_MEDIA[
                        _format.get("musicReleaseFormat") or "DigitalFormat"
                    ],
                    _format["name"],
                    _format.get("description") or "",
                )
            )
        return formats

    @staticmethod
    def add_track_alts(album: AlbumInfo, comments: str) -> AlbumInfo:
        # using an ordered set here in case of duplicates
        track_alts = ordset(PATTERNS["track_alt"].findall(comments))

        @lru_cache(maxsize=None)
        def get_medium_total(medium: int) -> int:
            starts = {1: "AB", 2: "CD", 3: "EF", 4: "GH", 5: "IJ"}[medium]
            return len(re.findall(rf"^[{starts}]", "\n".join(track_alts), re.M))

        medium = 1
        medium_index = 1
        if len(track_alts) == len(album.tracks):
            for track, track_alt in zip(album.tracks, track_alts):
                track.track_alt = track_alt
                track.medium_index = medium_index
                track.medium = medium
                track.medium_total = get_medium_total(medium)
                if track.medium_index == track.medium_total:
                    medium += 1
                    medium_index = 1
                else:
                    medium_index += 1
        return album
