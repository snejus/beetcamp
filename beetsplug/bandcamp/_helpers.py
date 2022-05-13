"""Module with a Helpers class that contains various static, independent functions."""
import itertools as it
import operator as op
import re
from functools import lru_cache, partial
from string import Template
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Pattern, Tuple, Union

from beets.autotag.hooks import AlbumInfo
from ordered_set import OrderedSet as ordset  # type: ignore

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
    | [.][0-9]+          # ISMVA002.1
)?
\b(?!["%]))"""
)
_cat_pat = _catalognum.template

CATNUM_PAT = {
    "with_header": re.compile(r"(?:^|\s)cat[\w .]+?(?:number:?|:) ?(\w[^\n,]+)", re.I),
    "start_end": re.compile(fr"((^|\n){_cat_pat}|{_cat_pat}(\n|$))", re.VERBOSE),
    "delimited": re.compile(fr"(?:[\[(])(?!.*MIX){_cat_pat}(?:[])]|$)", re.VERBOSE),
    "anywhere": re.compile(fr"(?<!,[ ])({_cat_pat}([ ]/[ ]{_cat_pat})?)", re.VERBOSE),
}

rm_strings = [
    "limited edition",
    r"^[EL]P( [0-9]+)?",
    r"^Vol(ume)?\W*(?!.*\)$)\d+",
    r"\((digital )?album\)",
    r"^va|va$|vinyl(-only)?|compiled by.*",
    r"free download|\([^()]*free(?!.*mix)[^()]*\)",
]
PATTERNS: Dict[str, Pattern] = {
    "split_artists": re.compile(r", - |, | (?:[x+/-]|//|vs|and)[.]? "),
    "clean_title": re.compile(
        fr"(([\[(])|(^| ))\*?(?i:({'|'.join(rm_strings)}))(?(2)[])]|( |$))"
    ),
    "clean_incl": re.compile(r"(\(?incl|\((inc|tracks|.*remix( |es)))([^)]+\)|.*)", re.I),
    "meta": re.compile(r'.*"@id".*', re.M),
    "remix_or_ft": re.compile(r" [\[(].*(?i:mix|edit|f(ea)?t([.]|uring)?).*"),
    "ft": re.compile(
        r" *((([\[(])| )f(ea)?t([. ]|uring)(?![^()]*mix)[^]\[()]+(?(3)[]\)])) *", re.I
    ),
    "track_alt": re.compile(r"^([ABCDEFGHIJ]{1,3}[0-6])(?:[^\w(]|_)+", re.I + re.M),
    "vinyl_name": re.compile(r"[1-5](?= ?(xLP|LP|x))|single|double|triple", re.I),
}


class Helpers:
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
        artists = list(map(lambda x: PATTERNS["ft"].sub("", x), artists))
        split = map(PATTERNS["split_artists"].split, ordset(artists))
        split_artists = ordset(map(str.strip, it.chain(*split))) - {""}
        split_artists_list = list(split_artists)

        for artist in split_artists_list:
            subartists = artist.split(" X ")
            if len(artists) == len(split_artists_list) or any(
                map(lambda x: x in split_artists, subartists)
            ):
                split_artists.discard(artist)
                split_artists.update(subartists)

            # ' & ' may be part of single artist name, so we need to be careful here
            # we check whether any of the split artists appears on their own
            subartists = artist.split(" & ")
            if len(subartists) > 1 and any(map(lambda x: x in split_artists, subartists)):
                split_artists.discard(artist)
                split_artists.update(subartists)
        return list(split_artists)

    @staticmethod
    @lru_cache(maxsize=None)
    def parse_catalognum(
        album="", disctitle="", description="", label="", tracks=None, artists=None
    ):
        # type: (str, str, str, Tuple[str], Tuple[str]) -> str
        """Try getting the catalog number looking at text from various fields."""
        tracks_str = "\n".join(tracks or [])
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

        def find(pat: Pattern, string: str) -> str:
            match = pat.search(string)
            return match.group(1).strip() if match else ""

        ignored = set(map(str.lower, artists or []))

        def not_ignored(option: str) -> bool:
            """Suitable match if:
            - is not empty
            - is not in any of the track names
            """
            return (
                bool(option)
                and option.lower() not in ignored
                and option not in tracks_str
            )

        try:
            return next(filter(not_ignored, it.starmap(find, cases)))
        except StopIteration:
            return ""

    @staticmethod
    def clean_name(name, *args, label="", remove_extra=False):
        # type: (str, str, str, bool) -> str
        """Return clean album name / track title.
        If `remove_extra`, remove info from within the parentheses (usually remix info).
        """
        replacements: List[Tuple[str, Union[str, Callable]]] = [
            (r"  +", " "),  # multiple spaces
            (r"\( +", "("),  # rubbish that precedes opening parenthesis
            (r" \)+|\)+$", ")"),
            ('"', ""),  # double quote anywhere in the string
            # spaces around dash in remixer names within parens
            (r"(\([^)]+) - ([^(]+\))", r"\1-\2"),
            (r"\[[A-Z]+[0-9]+\]", ""),
            # uppercase EP and LP, and remove surrounding parens / brackets
            (r"\S*(?i:(?:Double )?(\b[EL]P\b))\S*", lambda x: x.expand(r"\1").upper()),
            (r"- Reworked", "(Reworked)"),
        ]
        for pat, repl in replacements:
            name = re.sub(pat, repl, name).strip()

        for arg in [re.escape(arg) for arg in filter(op.truth, args)] + [
            r"Various Artists?\b(?! \w)"
        ]:
            if not re.search(fr"\w {arg} \w", name, re.I):
                name = re.sub(
                    fr"(^|[^'\])\w]|_|\b)+(?i:{arg})([^'(\[\w]|_|([0-9]+$))*", " ", name
                ).strip()

        if label and not re.search(fr"\w {label} \w|\w {label}$", name):
            pat = fr"(\W\W+{label}\W*|\W*{label}(\W\W+|$)|(^\W*{label}\W*$))(VA)?\d*"
            name = re.sub(pat, " ", name, re.I).strip()

        if remove_extra:
            # redundant information about 'remixes from xyz'
            name = PATTERNS["clean_incl"].sub("", name)
        return PATTERNS["clean_title"].sub("", name).strip(" -|/")

    @staticmethod
    def get_genre(keywords: Iterable[str], config: JSONDict) -> Iterable[str]:
        """Return a comma-delimited list of valid genres, using MB genres for reference.

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
        # use a list to keep the initial order
        genres: List[str] = []
        valid_mb_genre = partial(op.contains, GENRES)

        def is_included(kw: str) -> bool:
            return any(map(lambda x: re.search(x, kw), config["always_include"]))

        def valid_for_mode(kw: str) -> bool:
            if config["mode"] == "classical":
                return kw in GENRES

            words = map(str.strip, kw.split(" "))
            if config["mode"] == "progressive":
                return kw in GENRES or all(map(valid_mb_genre, words))

            return valid_mb_genre(kw) or valid_mb_genre(list(words)[-1])

        # expand badly delimited keywords
        split_kw = partial(re.split, r"[.] | #| - ")
        for kw in it.chain(*map(split_kw, keywords)):
            # remove full stops and hashes and ensure the expected form of 'and'
            kw = re.sub("[.#]", "", str(kw)).replace("&", "and")
            if kw not in genres and (is_included(kw) or valid_for_mode(kw)):
                genres.append(kw)

        unique_genres = set(genres)

        def duplicate(genre: str) -> bool:
            """Return True if genre is contained within another genre or if,
            having removed spaces from every other, there is a duplicate found.
            It is done this way so that 'dark folk' is kept while 'darkfolk' is removed,
            and not the other way around.
            """
            others = unique_genres - {genre}
            others = others.union(
                map(lambda x: x.replace(" ", "").replace("-", ""), others)
            )
            return any(map(lambda x: genre in x, others))

        return it.filterfalse(duplicate, genres)

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
                    FORMAT_TO_MEDIA[_format.get("musicReleaseFormat") or "DigitalFormat"],
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
            return len(re.findall(fr"^[{starts}]", "\n".join(track_alts), re.M))

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
