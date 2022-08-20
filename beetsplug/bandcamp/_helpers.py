"""Module with a Helpers class that contains various static, independent functions."""
import itertools as it
import operator as op
import re
from functools import lru_cache, partial
from string import Template
from typing import Any, Dict, Iterable, List, NamedTuple, Pattern, Tuple

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


_catalognum = Template(
    r"""(?<![]/@-])(\b
(?!\W|LC[ ]|VA[\d ]+|[EL]P\W|[^\n.]+[ ](?:20\d{2}|VA[ \d]+)|(?i:vol|disc|number))
(
      [A-Z][A-Z .]+\d{3}         # HANDS D300, CC ATOM 101
    | [A-Z-]{3,}\d+              # RIV4
    # dollar signs need escaping here since the $label below will be
    # substituted later, and we do not want to touch these two
    | [A-Z]{2,}[A-Z.$$-]*\d{2,}  # HS11, USE202, HEY-101, LI$$INGLE025
    | (?<!\w\W)[A-Z.]{2,}[ ]\d+  # OBS.CUR 9
    | [A-z]+-[A-z]+[ ]?\d+       # o-ton 119
    | \w+[A-z]0\d+               # 1ØPILLS018, fa036
    | [a-z]+(cd|lp|:)\d+         # ostgutlp45, reni:7
    | [A-z]+\d+-\d+              # P90-003
    | (?i:$label[ ]?[A-Z]*\d+[A-Z]*)
)
( # optionally followed by
      (?<=\d\d)-?[A-Z]+  # IBM001CD (needs at least two digits before the letter)
    | [.]\d+             # ISMVA002.1
)?
\b(?!["%]))"""
)
_cat_pat = _catalognum.template

CATNUM_PAT = {
    "with_header": re.compile(
        r"(?:^|\s)cat[\w .]+?(?:number\b:?|:) ?(\w[^\n,]+)", re.I
    ),
    "start_end": re.compile(rf"((^|\n){_cat_pat}|{_cat_pat}(\n|$))", re.VERBOSE),
    # enclosed by parens or square brackets, but not ending with MIX
    "delimited": re.compile(rf"(?:[\[(])(?!.*MIX){_cat_pat}(?:[])]|$)", re.VERBOSE),
    "anywhere": re.compile(rf"(?<!,[ ])({_cat_pat}([ ]/[ ]{_cat_pat})?)", re.VERBOSE),
}

_comp = re.compile
PATTERNS: Dict[str, Pattern] = {
    "split_artists": _comp(r", - |, | (?:[x+/-]|//|vs|and)[.]? "),
    "meta": _comp(r'.*"@id".*', re.M),
    "remix_or_ft": _comp(r" [\[(].*(?i:mix|edit|f(ea)?t([.]|uring)?).*"),
    "ft": _comp(
        r" *((([\[(])| )f(ea)?t([. ]|uring)(?![^()]*mix)[^]\[()]+(?(3)[]\)])) *", re.I
    ),
    "track_alt": _comp(
        r"^([A-J]{1,3}[12]?\d|[AB]+(?=\W{2,}))(?:(?!-\w)[^\w(]|_)+", re.I + re.M
    ),
    "vinyl_name": _comp(r"[1-5](?= ?(xLP|LP|x))|single|double|triple", re.I),
    "clean_incl": _comp(r" *(\(?incl|\((inc|tracks|.*remix( |es)))([^)]+\)|.*)", re.I),
    "tidy_eplp": _comp(r"\S*(?:Double )?(\b[EL]P\b)\S*", re.I),
}
rm_strings = [
    "limited edition",
    r"^[EL]P( \d+)?",
    r"^Vol(ume)?\W*(?!.*\)$)\d+",
    r"\((digital )?album\)",
    r"\(single\)",
    r"^va|va$|vinyl(-only)?|compiled by.*",
    r"free download|\([^()]*free(?!.*mix)[^()]*\)",
]

# fmt: off
CLEAN_PATTERNS = [
    (_comp(r" -(\S)"), r" - \1"),                   # hi -bye      -> hi - bye
    (_comp(r"(\S)- "), r"\1 - "),                   # hi- bye      -> hi - bye
    (_comp(r"  +"), " "),                           # hi  bye      -> hi bye
    (_comp(r"(- )?\( *"), "("),                     # hi - ( bye)  -> hi (bye)
    (_comp(r" \)+|\)+$"), ")"),                     # hi (bye ))   -> hi (bye)
    (_comp(r'(^|- )"([^"]+)"( \(|$)'), r"\1\2\3"),  # "bye" -> bye; hi - "bye" -> hi - bye
    (_comp(r"- Reworked"), "(Reworked)"),           # bye - Reworked -> bye (Reworked)
    (_comp(fr"(([\[(])|(^| ))\*?({'|'.join(rm_strings)})(?(2)[])]|( |$))", re.I), ""),
]
# fmt: on


class Helpers:
    @staticmethod
    def get_label(meta: JSONDict) -> str:
        try:
            return meta["albumRelease"][0]["recordLabel"]["name"]
        except (KeyError, IndexError):
            return meta["publisher"]["name"]

    @staticmethod
    def get_vinyl_count(name: str) -> int:
        conv = {"single": 1, "double": 2, "triple": 3}
        for match in PATTERNS["vinyl_name"].finditer(name):
            count = match.group()
            return int(count) if count.isdigit() else conv[count.lower()]
        return 1

    @staticmethod
    def split_artists(artists: Iterable[str]) -> List[str]:
        """Split artists taking into account delimiters such as ',', '+', 'x', 'X' etc.
        Note: featuring artists are removed since they are not main artists.
        """
        no_ft_artists = (PATTERNS["ft"].sub("", a) for a in artists)
        split = map(PATTERNS["split_artists"].split, ordset(no_ft_artists))
        split_artists = ordset(map(str.strip, it.chain(*split))) - {"", "more"}

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
        album="", disctitle="", description="", label="", tracks=None, artists=None
    ):
        # type: (str, str, str, Tuple[str], Tuple[str]) -> str
        """Try getting the catalog number looking at text from various fields."""
        cases = [
            (CATNUM_PAT["with_header"], description),
            (CATNUM_PAT["anywhere"], disctitle),
            (CATNUM_PAT["anywhere"], album),
            (CATNUM_PAT["start_end"], description),
            (CATNUM_PAT["anywhere"], description),
        ]
        if label:
            pat = re.compile(_catalognum.substitute(label=re.escape(label)), re.VERBOSE)
            cases.append((pat, "\n".join((album, disctitle, description))))

        tracks_str = " ".join([*(tracks or []), *(artists or [])]).lower()

        def find(pat: Pattern, string: str) -> str:
            """Return the match if it is not found in any of the track names."""
            m = pat.search(string)
            if m:
                catnum = m.group(1).strip()
                if catnum.lower() not in tracks_str:
                    return catnum
            return ""

        try:
            return next(filter(op.truth, it.starmap(find, cases)))
        except StopIteration:
            return ""

    @staticmethod
    def clean_name(name: str) -> str:
        for pat, repl in CLEAN_PATTERNS:
            name = pat.sub(repl, name).strip()
        return name

    @staticmethod
    def clean_album(name: str, *args: str, label: str = "") -> str:
        """Return clean album name.
        Catalogue number and artists to be removed are given as args.
        """
        name = PATTERNS["clean_incl"].sub("", name)
        name = re.sub(r"^\[(.*)\]$", r"\1", name)

        for arg in [re.escape(arg) for arg in filter(op.truth, args)] + [
            r"Various Artists?\b(?! \w)"
        ]:
            if not re.search(rf"\w {arg} \w", name, re.I):
                name = re.sub(
                    rf"(^|[^'\])\w]|_|\b)+(?i:{arg})([^'(\[\w]|_|(\d+$))*", " ", name
                ).strip()

        label_allow_pat = r"^{0}[^ ]|\({0}|\w {0} \w|\w {0}$".format(label)
        if label and not re.search(label_allow_pat, name):
            lpat = rf"(\W\W+{label}\W*|\W*{label}(\W\W+|$)|(^\W*{label}\W*$))(VA)?\d*"
            name = re.sub(lpat, " ", name, re.I).strip()

        name = Helpers.clean_name(name)
        # uppercase EP and LP, and remove surrounding parens / brackets
        name = PATTERNS["tidy_eplp"].sub(lambda x: x.group(1).upper(), name)
        return name.strip(" /")

    @staticmethod
    def get_genre(keywords, config, label):
        # type: (Iterable[str], JSONDict, str) -> Iterable[str]
        """Return a comma-delimited list of valid genres, using MB genres for reference.

        Initially, exclude keywords that are label names (unless they are valid MB genres)

        Verify each keyword's (potential genre) validity w.r.t. the configured `mode`:
          * classical: valid only if the _entire keyword_ matches a MB genre in the list
          * progressive: either above or if each of the words matches MB genre - since it
            is effectively a subgenre.
          * psychedelic: either one of the above or if the last word is a valid MB genre.
            This allows to be flexible regarding the variety of potential genres while
            keeping away from spammy ones.

        Once we have the list of keywords that make it through the mode filters,
        an additional filter is executed:
          * if a keyword is _part of another keyword_ (genre within a sub-genre),
            the more generic option gets excluded, for example,
            >>> get_genre(['house', 'garage house', 'glitch'], "classical")
            'garage house, glitch'
        """
        valid_mb_genre = partial(op.contains, GENRES)
        label_name = label.lower().replace(" ", "")

        def is_label_name(kw: str) -> bool:
            return kw.replace(" ", "") == label_name and not valid_mb_genre(kw)

        def is_included(kw: str) -> bool:
            return any(re.search(x, kw) for x in config["always_include"])

        def valid_for_mode(kw: str) -> bool:
            if config["mode"] == "classical":
                return valid_mb_genre(kw)

            words = map(str.strip, kw.split(" "))
            if config["mode"] == "progressive":
                return valid_mb_genre(kw) or all(map(valid_mb_genre, words))

            return valid_mb_genre(kw) or valid_mb_genre(list(words)[-1])

        unique_genres: ordset[str] = ordset()
        # expand badly delimited keywords
        split_kw = partial(re.split, r"[.] | #| - ")
        for kw in it.chain(*map(split_kw, keywords)):
            # remove full stops and hashes and ensure the expected form of 'and'
            kw = re.sub("[.#]", "", str(kw)).replace("&", "and")
            if not is_label_name(kw) and (is_included(kw) or valid_for_mode(kw)):
                unique_genres.add(kw)

        def duplicate(genre: str) -> bool:
            """Return True if genre is contained within another genre or if,
            having removed spaces from every other, there is a duplicate found.
            It is done this way so that 'dark folk' is kept while 'darkfolk' is removed,
            and not the other way around.
            """
            others = unique_genres - {genre}
            others = others.union(x.replace(" ", "").replace("-", "") for x in others)  # type: ignore[attr-defined] # noqa
            return any(genre in x for x in others)

        return it.filterfalse(duplicate, unique_genres)

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
                and "bundle" not in obj["name"].lower()
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
