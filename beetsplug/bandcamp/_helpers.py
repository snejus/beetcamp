import itertools as it
import operator as op
import re
from collections import Counter, defaultdict
from functools import partial
from string import Template
from typing import Any, Callable, Dict, Iterable, List, Pattern, Tuple, Union

from ordered_set import OrderedSet as ordset

from .genres_lookup import GENRES

JSONDict = Dict[str, Any]
MEDIA_MAP = {
    "VinylFormat": "Vinyl",
    "CDFormat": "CD",
    "CassetteFormat": "Cassette",
    "DigitalFormat": "Digital Media",
}

_catalognum = Template(
    r"""(?<![/@])(\b
(?!\W|VA[\d ]+|[EL]P\W|[^\n.]+[ ](?:[0-9]KG|20\d{2}|VA\d+)|AT[ ]0|GC1|HF[.])
(?!(?i:vol |mp3|christ|vinyl|disc|session|record|artist|the\ |maxi\ |rave\ ))
(?![^.]+shirt)
(
      [A-Z .]+\d{3}         # HANDS D300
    | [A-z ][ ]0\d{2,3}     # Persephonic Sirens 012
    | [A-Z-]{3,}\d+         # RIV4
    # dollar signs need escaping here since the $label below will be
    # substituted later, and we do not want to touch these two
    | [A-Z]+[A-Z.$$-]+\d{2,} # USE202, HEY-101, LI$$025
    | [A-Z.]{2,}[ ]\d{1,3}  # OBS.CUR 9
    | \w+[A-z]0\d+          # 1ØPILLS018, fa036
    | [a-z]+(cd|lp)\d+      # ostgutlp45
    | [A-z]+\d+-\d+         # P90-003
    | (?i:$label[ ]?[A-Z]*\d+[A-Z]*)
)
( # optionally followed by
      [ ]?[A-Z]     # IBM001V
    | [.][0-9]+     # ISMVA002.1
    | -?[A-Z]+      # PLUS8024CD
)?
\b(?!["]))"""
)
_cat_pattern = _catalognum.template

CATNUM_PAT = {
    "with_header": re.compile(
        r"(?:^|\s)cat[\w .]+?(?:number:?|:) ?(\w[^\n]+?)(\W{2}|\n|$)", re.I
    ),
    "start_end": re.compile(fr"((^|\n){_cat_pattern}|{_cat_pattern}(\n|$))", re.VERBOSE),
    "anywhere": re.compile(_cat_pattern, re.VERBOSE),
}

rm_strings = [
    "limited edition",
    r"^EP [0-9]+",
    r"^Vol(ume)?\W*\d",
    r"(digital )?album\)",
    r"va|vinyl|compiled by .*",
    r"free download|free dl|free\)",
]
PATTERNS: Dict[str, Pattern] = {
    "split_artists": re.compile(r", | (?:[x+/-]|vs)[.]? "),
    "clean_title": re.compile(fr"(?i:[\[(]?\b({'|'.join(rm_strings)})(\b\W*|$))"),
    "clean_incl": re.compile(r"(\(?incl|\((inc|tracks|.*remix( |es)))([^)]+\)|.*)", re.I),
    "meta": re.compile(r'.*"@id".*', re.M),
    "digital": [  # type: ignore
        re.compile(r"^(DIGI(TAL)? ?[\d.]+|Bonus\W{2,})\W*"),
        re.compile(
            r"[^\w\)]+(bandcamp[^-]+|digi(tal)?)(\W*(\W+|only|bonus|exclusive)\W*$)",
            re.I,
        ),
    ],
    "remix_or_ft": re.compile(r" [\[(].*(?i:mix|edit|f(ea)?t([.]|uring)?).*"),
    "ft": re.compile(r" *[( ]((?![^()]+?mix)f(ea)?t([. ]|uring)[^()]+)[)]? *", re.I),
    "track_alt": re.compile(r"([ABCDEFGH]{1,3}[0-6])\W+", re.I),
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
    def clear_digi_only(name: str) -> str:
        """Return the track title which is clear from digi-only artifacts."""
        clean_name = name
        for pat in PATTERNS["digital"]:  # type: ignore
            clean_name = pat.sub("", clean_name)
        return clean_name

    @staticmethod
    def split_artists(artists: Iterable[str]) -> List[str]:
        artists = list(map(lambda x: PATTERNS["ft"].sub("", x), artists))
        split = map(lambda x: PATTERNS["split_artists"].split(x), ordset(artists))
        split_artists = ordset(map(str.strip, it.chain(*split))) - {""}
        split_artists_list = list(split_artists)

        for artist in split_artists_list:
            subartists = artist.split(" X ")
            if len(list(artists)) == len(split_artists_list) or any(
                map(lambda x: x in split_artists, subartists)
            ):
                split_artists.discard(artist)
                split_artists.update(subartists)

            subartists = artist.split(" & ")
            if len(subartists) > 1 and any(map(lambda x: x in split_artists, subartists)):
                split_artists.discard(artist)
                split_artists.update(subartists)
        return list(split_artists)

    @staticmethod
    def get_trackalt(name: str) -> Tuple[str, str]:
        """Match track alt and remove it from the name, if found."""
        track_alt = ""
        match = PATTERNS["track_alt"].match(name)
        if match:
            track_alt = match.expand(r"\1").upper()
            name = name.replace(match.group(), "")
        return name, track_alt

    @staticmethod
    def parse_track_name(name: str, delim: str = "-") -> Dict[str, str]:
        track: Dict[str, str] = defaultdict(str)

        name, track_alt = Helpers.get_trackalt(name)
        # firstly attempt to split using appropriate spacing
        parts = name.split(f" {delim} ")
        if len(parts) == 1:
            # only if not split, then attempt at correcting it
            # some titles contain such patterns like below, so we want to avoid
            # splitting them if there's no reason to
            parts = re.split(fr" [{delim}]|[{delim}] ", name)
        parts = list(map(lambda x: x.strip(f" {delim}"), parts))

        title = parts.pop(-1)
        if not track_alt:
            # track alt may be found before the title, and not before the artist
            title, track_alt = Helpers.get_trackalt(title)

        # find the remixer
        match = re.search(r" *\( *[^)(]+?(?i:(re)?mix|edit)[)]", name, re.I)
        remixer = match.group() if match else ""

        # remove any duplicate artists keeping the order
        artist = ", ".join(ordset(parts))
        # remove remixer
        artist = artist.replace(remixer, "").strip(",")
        # split them taking into account other delimiters
        artists = ordset(Helpers.split_artists(parts))

        # remove remixer. We cannot use equality here since it is not reliable
        # consider Hello, Bye = Nice day (Bye Lovely Day Mix). Bye != Bye Lovely Day,
        # therefore we check whether Bye is contained in Bye Lovely Day instead
        for artist in filter(lambda x: x in remixer, artists.copy()):
            artists.discard(artist)
            artist = ", ".join(artists)

        track.update(title=title, artist=artist, track_alt=track_alt)

        # find the featuring artist, remove it from artist/title and make it available
        # in the `ft` field, later to be appended to the artist
        for entity in "artist", "title":
            match = PATTERNS["ft"].search(track[entity])
            if match:
                track[entity] = track[entity].replace(match.group(), " ").strip()
                track["ft"] = match.expand(r"\1")

        track["main_title"] = PATTERNS["remix_or_ft"].sub("", track["title"])
        return track

    @staticmethod
    def adjust_artists(tracks: List[JSONDict], aartist: str) -> List[JSONDict]:
        track_alts = set(filter(op.truth, (t["track_alt"] for t in tracks)))
        for t in tracks:
            # a single track_alt is missing -> check for a single letter, like 'A',
            # in the artist field
            if (
                len(tracks) > 1
                and not t["track_alt"]
                and not t["digi_only"]
                and len(track_alts) == len(tracks) - 1
            ):
                match = re.match(r"([A-B]{,2})\W+", t["artist"])
                if match:
                    t["track_alt"] = match.expand(r"\1")
                    t["artist"] = t["artist"].replace(match.group(), "", 1)

            if len(tracks) > 1 and not t["artist"]:
                if t["track_alt"] and len(track_alts) == 1:
                    # one of the artists ended up as a track alt, like 'B2'
                    t.update(artist=t.get("track_alt"), track_alt=None)
                else:
                    # use the albumartist
                    t["artist"] = aartist

        return tracks

    @staticmethod
    def parse_catalognum(album, disctitle, description, label, exclude):
        # type: (str, str, str, str, List[str]) -> str
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

        def find(pat: Pattern, string: str) -> str:
            try:
                return pat.search(string).groups()[0].strip()  # type: ignore
            except (IndexError, AttributeError):
                return ""

        ignored = set(map(str.casefold, exclude or []) or [None, ""])

        def not_ignored(option: str) -> bool:
            return bool(option) and option.casefold() not in ignored

        try:
            return next(filter(not_ignored, it.starmap(find, cases)))
        except StopIteration:
            return ""

    @staticmethod
    def get_duration(source: JSONDict) -> int:
        try:
            h, m, s = map(int, re.findall(r"[0-9]+", source["duration"]))
            return h * 3600 + m * 60 + s
        except KeyError:
            return 0

    @staticmethod
    def clean_name(name, *args, label="", remove_extra=False):
        # type: (str, str, str, bool) -> str
        """Return clean album name / track title.
        If `remove_extra`, remove info from within the parentheses (usually remix info).
        """
        replacements: List[Tuple[str, Union[str, Callable]]] = [
            (r"  +", " "),  # multiple spaces
            (r"\( +|(- )?\(+", "("),  # rubbish that precedes opening parenthesis
            (r" \)+|(?<=(?i:.mix|edit))\)+$", ")"),
            ('"', ""),  # double quote anywhere in the string
            # spaces around dash in remixer names within parens
            (r"(\([^)]+) - ([^(]+\))", r"\1-\2"),
            (r"[\[(][A-Z]+[0-9]+[\])]", ""),
            # uppercase EP and LP, and remove surrounding parens / brackets
            (r"(\S*(\b(?i:[EL]P)\b)\S*)", lambda x: x.expand(r"\2").upper()),
        ]
        for pat, repl in replacements:
            name = re.sub(pat, repl, name).strip()
        for arg in filter(op.truth, args):
            esc = re.escape(arg)
            name = re.sub(fr"[^'\])\w]*(?i:{esc})[^'(\[\w]*", " ", name).strip()

        rm = f"(Various Artists?|{label})" if label else "Various Artists?"
        name = re.sub(
            fr"(?i:(\W\W+{rm}\W*|\W*{rm}(\W\W+|$)|(^\W*{rm}\W*$)))", " ", name
        ).strip()
        if remove_extra:
            # redundant information about 'remixes from xyz'
            name = PATTERNS["clean_incl"].sub("", name)
        return PATTERNS["clean_title"].sub("", name).strip(" -|/")

    @staticmethod
    def clean_ep_lp_name(album: str, artists: List[str]) -> str:
        """Parse album name - which precedes 'LP' or 'EP' in the release title.
        Attempt to remove artist names from the parsed string:
        * If we're only left with 'EP', it means that the album name is made up of those
          artists - in that case we keep them.
        * Otherwise, we will end up cleaning a release title such as 'Artist Album EP',
          where the artist is not clearly separated from the album name.
        """
        match = re.search(r".+[EL]P", re.sub(r".* [-|] | [\[(][^ ]*|[\])]", "", album))
        if not match:
            return ""
        album_with_artists = match.group().strip()
        clean_album = Helpers.clean_name(album_with_artists, *artists)
        return album_with_artists if len(clean_album) == 2 else clean_album

    @staticmethod
    def clean_track_names(names: List[str], catalognum: str = "") -> List[str]:
        """Remove catalogue number and leading numerical index if they are found."""
        if catalognum:
            names = list(map(lambda x: Helpers.clean_name(x, catalognum), names))

        len_tot = len(names)
        if len_tot > 1 and sum(map(lambda x: int(x[0].isdigit()), names)) > len_tot / 2:
            pat = re.compile(r"^\d+\W+")
            names = list(map(lambda x: pat.sub("", x), names))
        return names

    @staticmethod
    def track_delimiter(names: List[str]) -> str:
        """Return the track parts delimiter that is in effect in the current release.
        In some (unusual) situations track parts are delimited by a pipe character
        instead of dash.

        This checks every track looking for the first character (see the regex for
        exclusions) that splits it. The character that split the most and
        at least half of the tracklist is the character we need.
        """

        def get_delim(string: str) -> str:
            match = re.search(r" ([^\w&()+ ]) ", string)
            return match.expand(r"\1") if match else "-"

        most_common = Counter(map(get_delim, names)).most_common(1)
        if not most_common:
            return ""
        delim, count = most_common.pop()
        return delim if (len(names) == 1 or count > len(names) / 2) else "-"

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
            others = others.union(map(lambda x: x.replace(" ", ""), others))
            return any(map(lambda x: genre in x, others))

        return it.filterfalse(duplicate, genres)

    @staticmethod
    def _get_media_reference(meta: JSONDict) -> JSONDict:
        """Get release media from the metadata, excluding bundles.
        Return a dictionary with a human mapping (Digital|CD|Vinyl|Cassette) -> media.
        """

        def is_bundle(fmt: JSONDict) -> bool:
            return "bundle" in (fmt.get("name") or "").casefold()

        media: Dict[str, JSONDict] = {}
        for _format in it.filterfalse(is_bundle, meta["albumRelease"]):
            try:
                medium = _format["musicReleaseFormat"]
            except KeyError:
                continue
            human_name = MEDIA_MAP[medium]
            media[human_name] = _format
        return media
