import re
from typing import Any, Dict
from unicodedata import normalize

from beets.autotag.hooks import TrackInfo
from pycountry import countries, subdivisions

from ._metaguru import COUNTRY_OVERRIDES, DIGI_MEDIA, Helpers

JSONDict = Dict[str, Any]


def get_country(loc: str) -> str:
    try:
        name = normalize("NFKD", loc).encode("ascii", "ignore").decode()
        return (
            COUNTRY_OVERRIDES.get(name)
            or getattr(countries.get(name=name, default=object), "alpha_2", None)
            or subdivisions.lookup(name).country_code
        )
    except (ValueError, LookupError):
        return "XW"


def parse_title(source: str, title: str) -> JSONDict:
    delim = r"([-&|x]|w/|__)"
    _delim = rf" {delim} "

    index_pat = r"(?P<full_index>[\[# 0]+(?P<index>[\d.]+\b)\]?)"
    artist_pat = rf"(?P<artist>.+(?!{delim}))"
    album_pat = rf"#*(?P<album>.+(?!{delim}))"
    label_pat = r"(?P<full_label> \[(?P<label>[^\]]+)\])"

    data: JSONDict = {"artist": source, "title": title}
    m = re.search(r" [^ ]*live[^ ]*", data["title"], re.I)
    if m:
        data["title"] = data["title"].replace(m.group(0), "")
        data["live"] = True
    for pat in (
        # discast
        rf"^{album_pat}{_delim}{index_pat}{_delim}{artist_pat}{delim}.*$",
        rf"^{album_pat}{_delim}{index_pat}{_delim}{artist_pat}$",
        # DISSENTIENT.SPACE
        rf"^{index_pat}{_delim}{artist_pat}{delim}$",
        # Ismcast, DUSKCAST, POSSESSION, DETECT
        rf"^{album_pat}{index_pat}{_delim}{artist_pat}({delim}.*$|{label_pat})",
        # Axxidcast
        rf"^{album_pat}{_delim}{artist_pat}{_delim}(Live )?{index_pat}$",
        # CRUDE MIX
        rf"^{album_pat} {index_pat}{_delim}{artist_pat}$",
        # SACHSENTRANCE PODCAST
        rf"^{artist_pat}{_delim}{album_pat} {index_pat}$",
    ):
        # print(pat)
        m = re.search(pat, title)
        if m:
            mdata = m.groupdict()
            data.update(mdata)
            full_index = data.pop("full_index", "")
            if full_index and title.startswith(full_index):
                title = title.split(full_index)[1].strip(" -|")
            full_label = data.pop("full_label", "")
            if full_label:
                title = title.replace(full_label, "")
            data["title"] = title
            break

    index = data.pop("index", "")
    if "." not in index:
        index = index.lstrip("0")
    data["track"] = index

    title, artist = data["title"], data["artist"]
    if title and title.startswith(artist):
        data["title"] = re.sub(rf"{artist}{_delim}", "", title)

    data["artist"] = ", ".join(Helpers.split_artists([data["artist"]]))
    return data


def get_soundcloud_track(data: JSONDict, config: JSONDict) -> TrackInfo:
    from dateutil.parser import isoparse

    userdata = data.get("user") or {}
    date = isoparse(data["display_date"])
    url = data["permalink_url"]
    loc = userdata.get("country_code") or userdata.get("city") or ""
    track = TrackInfo(
        title=data["title"],
        track_id=url,
        isrc=(data.get("publisher_metadata") or {}).get("isrc"),
        length=round(data["duration"] / 1000) - 1,
        label=(data.get("label_name") or userdata["username"]).strip(" /"),
        media=DIGI_MEDIA,
        genre=", ".join(
            Helpers.get_genre(
                keywords=list(
                    map(str.casefold, re.split(r" ?[-,/] ", data.get("genre") or ""))
                ),
                config=config,
            )
        ),
        country=loc if len(loc) == 2 else get_country(loc),
        comments=data.get("description") or None,
        day=date.day,
        month=date.month,
        year=date.year,
        data_source="soundcloud",
        data_url=url,
        artist_id=userdata["urn"],
        artist=userdata["username"],
        artwork_url=(data.get("artwork_url") or "").replace("-large", "-t500x500"),
        visual_url=(userdata.get("visuals") or {})
        .get("visuals", [{}])[0]
        .get("visual_url"),
    )

    parsed_track = parse_title(track.label, track.title)
    track.update(parsed_track)

    track.albumtype = "single"
    albumtypes = {track.albumtype}
    if track.length > 2000:
        track.albumtype = "broadcast"
        albumtypes = {"dj-mix", "broadcast"}
    if track.pop("live", None):
        albumtypes.add("live")
    track.albumtypes = "; ".join(sorted(albumtypes))
    if "album" in track:
        track.albumstatus = "Official"

    track.albumartist = ""

    if track.get("album"):
        track.update(albumartist=track.get("label") or track.get("artist"))

    track.title = parsed_track.pop("title", None)
    if not track.title:
        track.title = f"{track.album} {track.track}"

    return track
