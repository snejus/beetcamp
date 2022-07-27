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
    index_pat = r"(?:\s|0)*(?P<index>[1-9][0-9]*)"
    artist_pat = r"(?P<artist>[^\[]?[^\[_-]+[[]?)"
    title_pat = r"(?P<title>[^-]+)"
    data: JSONDict = {}
    if title.startswith("DETECT"):
        data["album"] = "DETECT"
        pat = rf"\[{index_pat}\] - {title_pat}"
    elif title.startswith("Morph"):
        data["album"] = "Morph"
        pat = rf"{index_pat} {artist_pat}"
    elif "DISSENTIENT" in source:
        data["album"] = source
        pat = rf"{index_pat}[ .-]+(?P<title>{artist_pat}.*)$"
    elif title.startswith("Ismcast"):
        data["album"] = "Ismcast"
        pat = rf"{index_pat} - (?P<title>{artist_pat}.*)$"
    elif title.startswith("DUSKCAST"):
        data["album"] = "DUSKCAST"
        pat = rf"{index_pat} [|] {artist_pat}"
    elif title.startswith("Axxidcast"):
        data["album"] = "Axxidcast"
        pat = r"w/ (?P<artist>[^-]+) - .* (?P<index>[0-9.]+)$"
    elif title.startswith("CRUDE"):
        data["album"] = "CRUDE MIX Series"
        data["label"] = "CRUDE"
        pat = rf"CRUDE MIX\D+{index_pat} - {artist_pat}(_+(?P<title>[^_]+))?$"
    elif "SlamRadio" in title:
        data["album"] = "SlamRadio"
        pat = rf"- {index_pat} - {artist_pat}$"
    elif title.startswith("HER "):
        data["album"] = "HER Transmission"
        pat = rf"{index_pat}: {artist_pat}$"
    elif title.startswith("BunkerBauer"):
        data["album"] = "BunkerBauer Podcast"
        pat = rf"Podcast {index_pat} {artist_pat}$"
    elif title.startswith("HRA PODCAST"):
        data["album"] = "HRA PODCAST"
        pat = rf"PODCAST {index_pat} // {artist_pat}$"
    elif title.startswith("Voight-Kampff Podcast"):
        data["album"] = "Voight-Kampff Podcast"
        pat = rf"(?P<title>Episode {index_pat}) // {artist_pat}$"
    elif title.startswith("Reclaim Your"):
        data["album"] = "Reclaim Your City"
        pat = rf"City {index_pat} [|] {artist_pat}$"
    elif "Boiler Room" in title:
        data["album"] = "Boiler Room"
        pat = rf"{artist_pat} [|] Boiler Room x {title_pat}$"
    elif title.startswith("STRECK PO"):
        data["label"], data["album"] = "STRECK", "STRECK PODCAST"
        pat = rf"{index_pat} [|] {artist_pat}"
    elif title.startswith("Hard Dance"):
        data["album"] = "Hard Dance"
        pat = rf"{index_pat} [:] {artist_pat}"
    elif "SLIT " in title:
        data["album"] = "SLIT"
        pat = rf"{artist_pat} [|] SLIT - {title_pat}$"
    elif "FOLD Invites" in title:
        data["label"], data["album"], data["title"] = "FOLD", "FOLD Invites", title
        pat = rf"Invites {artist_pat}$"
    elif "IN•FER•NAL" in title:
        data["label"], data["album"] = "IN•FER•NAL", "IN•FER•NAL PODCAST"
        data["title"] = title.rsplit(" - ", 1)[0]
        pat = rf"PODCAST #{index_pat} - {artist_pat}$"
    elif "PUPPY MIX" in title:
        data["label"], data["album"] = "PUPPY", "PUPPY MIX"
        pat = rf".PUPPY MIX {index_pat}. \* {artist_pat}$"
    elif title.startswith("DEADCAST"):
        data["album"] = "DEADCAST"
        pat = rf"DEADCAST{index_pat} x {artist_pat}( [\[](?P<label>[^]]+)[]])?$"
    elif title.startswith("Digital Tsunami"):
        data["label"] = data["album"] = "Digital Tsunami"
        pat = rf"Digital Tsunami {index_pat} - {artist_pat}"
    elif title.startswith("ANGELSCAST"):
        data["label"] = "angels gun club"
        data["album"] = "ANGELSCAST"
        pat = rf"ANGELSCAST {index_pat} - {artist_pat}"
    elif re.match(r"Hardcore \d+", title):
        data["album"], data["title"] = "Hardcore", title
        pat = rf"Hardcore {index_pat}"
    elif source == "Sarunas":
        data["artist"] = "SN"
        data["title"] = title
        data["country"] = "GB"
        data["label"] = ""
        if "SN MIX" in title:
            data["albumartist"] = "SN"
            data["album"] = "SN MIX"
        else:
            data["album"] = ""
        pat = "aaaaaa"
    else:
        pat = rf"{artist_pat} - {title_pat}"
    if pat:
        match = re.search(pat, title)
        if match:
            mdata = match.groupdict()
            data.update(mdata)

    data["track"] = data.get("index")
    artist = data.get("artist") or ""
    if not artist:
        data["artist"] = source
    else:
        m = re.search(r" [^ ]*live[^ ]*", artist, re.I)
        if m:
            data["title"] = data["artist"]
            data["artist"] = data["artist"].replace(m.group(0), "")
            data["live"] = True
        if data["artist"] == data.get("title") or "":
            data.pop("title", None)

    return data


def get_soundcloud_track(data: JSONDict, config: JSONDict) -> TrackInfo:
    from dateutil.parser import isoparse

    userdata = data.get("user") or dict()
    date = isoparse(data["display_date"])
    url = data["permalink_url"]
    loc = userdata.get("country_code") or userdata.get("city") or ""
    track = TrackInfo(
        title=data["title"],
        index=0,
        track_id=url,
        isrc=(data.get("publisher_metadata") or {}).get("isrc"),
        length=round(data["duration"] / 1000) - 1,
        label=data.get("label_name") or userdata["username"],
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
    )
    print(track)
    artwork_url = (data.get("artwork_url") or "").replace("-large", "-t500x500")
    if artwork_url:
        track["artwork_url"] = artwork_url
    visual_url = (
        (userdata.get("visuals") or {}).get("visuals", [{}])[0].get("visual_url")
    )
    if visual_url:
        track["visual_url"] = visual_url

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
        track.update(
            album_id=userdata.get("station_urn") or url,
            albumartist=track.get("label") or track.get("artist"),
        )
        parsed_title = parsed_track.get("title")
        if not parsed_title:
            track.title = f"{track.album} {track.index}"

    return track
