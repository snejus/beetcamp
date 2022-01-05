import re
from typing import Any, Dict

from beets.autotag.hooks import TrackInfo

from . import DEFAULT_CONFIG, console
from ._metaguru import DIGI_MEDIA, Helpers, Metaguru

JSONDict = Dict[str, Any]


def parse_title(source: str, title: str) -> JSONDict:
    index_pat = r"(?P<index>[1-9][0-9]+)"
    artist_pat = r"(?P<artist>[^_]+)"
    artitle = r"(?P<title>.*)"
    data: JSONDict = {}
    if title.startswith("DETECT"):
        data["album"] = "DETECT"
        pat = fr"\[{index_pat}\] - {artitle}"
    elif title.startswith("Morph"):
        data["album"] = "Morph"
        pat = fr"{index_pat} {artist_pat}"
    elif "DISSENTIENT" in source:
        data["album"] = source
        pat = fr"{index_pat}[ .-]+(?P<title>{artist_pat}.*)$"
    elif title.startswith("Ismcast"):
        data["album"] = "Ismcast"
        pat = fr"{index_pat} - (?P<title>{artist_pat}.*)$"
    elif title.startswith("DUSKCAST"):
        data["album"] = "DUSKCAST"
        pat = fr"{index_pat} [|] {artist_pat}"
    elif title.startswith("Axxidcast"):
        data["album"] = "Axxidcast"
        pat = r"w/ (?P<artist>[^-]+) - .* (?P<index>[0-9.]+)$"
    elif title.startswith("CRUDE"):
        data["album"] = "CRUDE MIX"
        data["label"] = "CRUDE"
        pat = fr"CRUDE MIX\D+{index_pat} - {artist_pat}(_+(?P<title>[^_]+))?$"
    elif "SlamRadio" in title:
        data["album"] = "SlamRadio"
        pat = fr"- {index_pat} - {artist_pat}$"
    elif title.startswith("HER "):
        data["album"] = "HER Transmission"
        pat = fr"{index_pat}: {artist_pat}$"
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
    else:
        pat = (
            r"(^| )"
            r"(?i:(?P<album>\w+(cast)?)( presents|#| ?0+))?[ 0]*"
            fr"{index_pat}(?:[ x-]+)"
            r"(?P<artist>(?i:dj [^-]+)|[^\(\[]+)?[ -]*"
        )
    match = re.search(pat, title)
    if match:
        mdata = match.groupdict()
        data.update(mdata)

    print(data)
    data["track"] = data.get("index")
    artist = data.get("artist") or ""
    if not artist:
        data["artist"] = source
    else:
        data["artist"] = (data.get("artist") or "").replace(" live", "").replace(" (liveset)", "")
        if data["artist"] == data.get("title") or "":
            data.pop("title", None)

    return data


def get_soundcloud_track(
    data: JSONDict, config: JSONDict = DEFAULT_CONFIG["genre"]
) -> TrackInfo:
    # console.print(data)
    from dateutil.parser import isoparse

    userdata = data.get("user") or dict()
    date = isoparse(data["display_date"])
    url = data["permalink_url"]
    loc = userdata.get("country_code") or userdata.get("city") or ""
    track = TrackInfo(
        title=data["title"],
        index=0,
        # track_id=data["urn"],
        track_id=url,
        isrc=(data.get("publisher_metadata") or {}).get("isrc"),
        length=round(data["duration"] / 1000),
        label=data.get("label_name") or userdata["username"],
        media=DIGI_MEDIA,
        genre=", ".join(
            Helpers.get_genre(
                keywords=list(
                    map(str.casefold, re.split(r" ?[-,/] ", data.get("genre") or ""))
                ),
                genre_config=config,
            )
        ),
        country=loc if len(loc) == 2 else Metaguru.get_country(loc),
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
    visual_url = (userdata.get("visuals") or {}).get("visuals", [{}])[0].get("visual_url")
    if visual_url:
        track["visual_url"] = visual_url

    parsed_track = parse_title(track.label, track.title)
    track.update(parsed_track)

    if track.length > 2000:
        track.albumtype = "broadcast"
        albumtypes = ["dj-mix", "broadcast"]
        if "live" in (track.get("title") or ""):
            albumtypes.append("live")
        track.albumtypes = "; ".join(albumtypes)

    if track.get("album"):
        track.update(
            albumstatus="Official",
            album_id=userdata.get("station_urn") or url,
            albumartist=track.get("label") or track.get("artist"),
        )
        parsed_title = parsed_track.get("title")
        if not parsed_title:
            track.title = f"{track.album} {track.index}"

    return track
