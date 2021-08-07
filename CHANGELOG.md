## [0.10.1] 2021-09-13

### Fixed

- Fixed #18 by handling cases when a track duration is not given.
- Fixed #19 where artist names like **SUNN O)))** would get incorrectly mistreated by
  the album name cleanup logic due to multiple consecutive parentheses. The fix involved
  adding some rules around it: they are now deduped _only if_

  - they are preceded with a space
  - or they enclose remix / edit info and are the last characters in the album name

- Fixed #20 where dynamically obtained label names used in further REs caused `re.error`
  since they were not appropriately escaped (for example, `label: /m\ records`).

Thanks @arogl for reporting each of the above!

- `album`: Keep label in the album name if it's immediately followed by an apostrophe. An
  example scenario:
  - `label: Mike`
  - `album: Mike's Creations`

[0.10.1]: https://github.com/snejus/beetcamp/releases/tag/0.10.1

## [0.10.0] 2021-09-10

### Fixed

- General

  - Fixed the logic which fetches the additional data fields (`comments` and `lyrics`). It
    used to cause unwanted behavior _since it wrote the files when `write: yes`_ was
    enabled in the beets config. Now, it's activated through the `import_task_apply` hook
    and _adjusts the metadata_ (beets db) without ever touching the files directly.
  - Unexpected errors are now printed instead of causing `beets` to quit immediately.

- `track.track_alt`: handle `A1 - Title` and `A1 - Artist - Title` when alt index is not
  followed by a full stop.
- `track.title`: handle cases like `Artist -Title` when there is no space between the dash
  and the title
- `country`: **Washington, D.C.** and **South Korea** have not been parsed correctly and
  thus releases have been defaulting to **XW**. This is now fixed.

### Updated

- `track.artist`: in rare cases when bandcamp specify that track artist **is the author of
  the remix (not the albumartist)**, append the remix author to the artist field such that

  ```
  Main Artist - Title (Someone Remix) ->
    albumartist: Main Artist
    artist: Main Artist, Someone
    title: Title (Someone Remix)
  ```

- `track.title`:

  - Handle cases like **Artist -Title** / **Artist- Title** when there is no space between
    the dash and the title or artist
  - Fixed _digital only_ cleaner which would previously remove the string **Only** when
    it's found on its own
  - Accept [**¯\\_(ツ)_/¯**](https://clandestinerecords.bandcamp.com/track/--7) as valid title
  - Clean up **( Remix )** -> **(Remix)**

- `country`: **Washington, D.C.** and **South Korea** have not been parsed correctly and
  thus releases have been defaulting to **XW**. This is now fixed.

### Updated

- `catalognum`:

  - Treat **VA[0-9]+**, **vinyl [0-9]+**, **triple [0-9]+**, **ep 12** as invalid (case
    insensitive)
  - Handle single digits (like **ROAD4**) as valid (until now we required at least two)
  - Handle catalognums in parentheses, like **(ISM001)**
  - Handle a period or a dash in the non-digit part, like **OBS.CUR 12**, **O-TON 113**
  - Allow a single capital letter after the digits, like **IBM001V**
  - Allow the catalognum to start with a non-capital letter, like **fa010**

- `album` and `track.title`: little clean up: replace multiple consecutive spaces with a
  single one and remove all double quotes

- `album`:

  - Only remove label from the album name if `albumtype` is not a compilation
  - Remove **(FREE)**, **(FREE DL)**, **VA**, **_(Incl._ some artists _remixes)_** and alike
  - Improved the way **Various Artists** are cleaned up when catalognum is available

- `albumartist`:

  - If **various** is specified as the albumartist, make it **Various Artists**
  - When the label have set their name as the albumartist in every field, and if the
    actual albumartist could be inferred from the album name, use the inferred name.
  - If _all_ release tracks have the same artist, assume they are the albumartist

- `albumtype`: treat 4-track release as a valid candidate for a compilation / VA albumtype

## [0.9.3] 2021-08-01

### Updated

- Bandcamp json updates:
  - `release_date`: `datePublished` field now tells the correct release date so now we use
    it instead of parsing the plain html.
  - `label`: some releases embed the `recordLabel` field into the json data - it now gets
    prioritized over the publisher name when it is available.
- `track.title`: clean up `*digital only*` properly. Previously we did not account for
  asterixes

### Fixed

- A regression from `0.9.2` which caused double initialization of the plugin. If your
  initial tracks metadata has the album name, the results should again be returned
  instantly.
- Searching by release ID where the ID is not a bandcamp URL should now be ignored by the
  plugin. Thanks @arogl.

## [0.9.2] 2021-07-17

### Fixed

- Thanks @arogl for fixing a FutureWarning apparent thrown in Python 3.7.
- Thanks @brianredbeard for reporting that the plugin writes file metadata even when this
  is disabled globally. This is now fixed.
- singleton album/artist: cases when the release name contains only the track name are now
  parsed correctly.

### Removed

- Removed deprecated `lyrics` configuration option.

### Added

- Added a github action to run ci for `master` and `dev` branches. For now it's just a minimal
  configuration and will probably get updated soon.

## [0.9.1] 2021-06-04

### Fixed

- `album.albumstatus`: If the release date is _today_, use **Official** and not
  **Promotional**.
- `album.albumtype`:
  - Until now we have only set _single_ track releases to have the _single_ type. This has
    been fixed regarding the MusicBrainz description: release composed of the same title
    and multiple remixes is a single.
  - Use `ep` only if _EP_ is mentioned either in the album name or the disc title.
- `album.catalognum`: Make the _DISCTITLE_ uppercase before looking for the catalogue
  number.
- `album.media`: Exclude anything that contains _bundle_ in their names. These usually
  contain additional releases that we do not need.
- `track.title`: Clean `- DIGITAL ONLY` (and similar) when it's preceded by a dash and not
  enclosed by parens or square brackets.
- `track.track_alt`: Having witnessed a very creative track title **E7-E5**, limit the
  `track_alt` field number to the range **0-6**.
- Committed a JSON testcase which was supposed to be part of `0.9.0`.

### Added

- Extend `url2json` with `--tracklist-for-tests` to ease adding new testcases.

## [0.9.0] 2021-06-01

### Fixed

- If track artist is given in the `byArtist` field of the track JSON resource, it is used.
  (Fixes #13, thanks @xeroxcat).
- Parse cases like `Catalogue:CAT-000` from the description correctly when the space is missing.

### Added

- The `comments` field now includes the media description and credits.
- The description is searched for artist and album names in addition to the catalogue
  number.

### Updated

- All testcases are now pretty JSON files - this should bring more transparency around
  the adjustments that Bandcamp make in the future (once they get updated). The `url2json`
  tool has `-u` flag that updates them automatically.

- Parsing

  - `(FREE)`, `(free download)`-like strings are now removed from the track names.
  - `[Vinyl]` is excluded from album names.

## [0.8.0] 2021-04-20

### Fixed

- Responded to bandcamp html updates:

  - `artist_id` now lies under `publisher` resource (previously `byArtist`) in the
    `/track/<name>` output when the track is part of an album.
  - `url` field has disappeared from track objects - using `@id` instead.
  - `country` and `label` fields are now found in the JSON data and thus we make use of it
  - Updated and truncated test html files since we now only need to see the beginning of
    the document.

- Parsing / logic:

  - Token `feat.` is now recognised as a valid member of the `artist` field.
  - `free download`, `[EP|LP]`, `(EP|LP)`, `E.P.`, `LP` are now cleaned from the album name.
  - Updated `albumtype` logic: in some `compilation` cases track artists would go missing
    and get set to _Various Artists_ - instead it now defaults to the original
    `albumartist`.
  - Handling a couple of edge cases in the track name / title, and catalognum parsers.

### Updated

- Package:

  - Moved `beets` from main to dev dependencies.
  - Updated supported python versions range (3.6.x-3.9.x)
  - Added pylint.
  - Removed dependency on `packaging` - using `pkg_resources` instead.

- Internal:

  - Reintroduced `@cached_property` across most of the fields having found how often certain
    ones get called.

### Added

- Release description is now checked for the catalogue number.
- Added a test based on parsing _the JSON output_ directly without having to parse the
  entire HTML. Bandcamp have been moving away from HTML luckily, so let's hope the trend
  continues.
- Added a tiny cmd-line tool `url2json` which simply outputs either a compacted or a
  human version of the JSON data that is found for the given bandcamp URL.

## [0.7.1] 2021-03-15

### Fixed

- Fixed singleton regression where track list was getting read incorrectly.

## [0.7.0] 2021-03-15

### Added

- For those who use `beets >= 1.5.0`, singleton tracks are now enriched with similar metadata
  to albums (depending on whether they are found of course):

  - `album`: **Artist - Track** usually
  - `albumartist`
  - `albumstatus`
  - `albumtype`: `single`
  - `catalognum`
  - `country`
  - `label`
  - `medium`, `medium_index`, `medium_total`
  - release date: `year`, `month`, `day`

- Album names get cleaned up. The following, if found, are removed:

  - Artist name (unless it's a singleton track)
  - Label name
  - Catalogue number
  - Strings
    - **Various Artists**
    - **limited edition**
    - **EP** (only if it is preceded by a space)
  - If any of the above are preceded/followed by **-** or **|** characters, they are
    removed together with spaces around them (if they are found)
  - If any of the above (except **EP**) are enclosed in parentheses or square brackets,
    they are also removed.

  Examples:

      Album - Various Artists -> Album
      Various Artists - Album -> Album
      Album EP                -> Album
      [Label] Album EP        -> Album
      Artist - Album EP       -> Album
      Label | Album           -> Album
      Album (limited edition) -> Album

- Added _recommended_ installation method in the readme.
- Added tox tests for `beets < 1.5` and `beets > 1.5` for python versions from 3.6 up to
  3.9.
- Sped up reimporting bandcamp items by checking whether the URL is already available
  before searching.
- Parsing: If track's name includes _bandcamp digital (bonus|only) etc._, **bandcamp** part gets
  removed as well.

### Changed

- Internal simplifications regarding `beets` version difference handling.

### Fixed

- Parsing: country/location name parser now takes into account punctuation such as in
  `St. Louis` - it previously ignored full stops.

## [0.6.0] 2021-02-10

### Added

- Until now, the returned fields have been limited by what's available in
  _search-specific_ `TrackInfo` and `AlbumInfo` objects. The marks the first attempt of
  adding information to _library_ items that are available at later import stages.

  If the `comments` field is empty or contains `Visit <artist-page>`, the plug-in
  populates this field with the release description. This can be reverted by including it
  in a new `exclude_extra_fields` list option.

### Deprecated

- `lyrics` configuration option is now deprecated and will be removed in one of the
  upcoming releases (0.8.0 / 0.9.0 - before stable v1 goes out). If lyrics aren't needed,
  it should be added to the `exclude_extra_fields` list.

### Fixed

- The `albumartist` that would go missing for the `beets 1.5.0` import stage has now safely returned.

## [0.5.7] 2021-02-10

### Fixed

- For the case when a track or an album is getting imported through the id / URL mode, we now
  check whether the provided URL is a Bandcamp link. In some cases parsing foreign URLs
  results in decoding errors, so we'd like to catch those URLs early. Thanks @arogl for
  spotting this.

## [0.5.6] 2021-02-08

### Fixed

- Bandcamp updated their html format which broke track duration parsing. This is now fixed
  and test html files are updated.

- Fixed track name parser which would incorrectly parse a track name like `24 hours`,
  ignoring the numbers from the beginning of the string.

- Locations that have non-ASCII characters in their names would not be identified
  (something like _Montreal, Québec_) - now the characters are converted and
  `pycountry` does understand them.

- Fixed an edge case where an EP would be incorrectly misidentified as an album.

### Updated

- Catalogue number parser now requires at least two digits to find a good match.

## [0.5.5] 2021-01-30

### Updated

- Country name overrides for _Russia_ and _The Netherlands_ which deviate from the
  official names.
- Track names:
  - If _digital_ and _exclusive_ are found in the name, it means it's digital-only.
  - Artist / track splitting logic now won't split them on the dash if it doesn't have
    spaces on both sides.
  * `track_alt` field may now contain numerical values if track names start with them.
    Previously, only vinyl format was supported with the `A1` / `B2` notation.

## [0.5.4] 2021-01-25

### Added

- Previously skipped, not-yet-released albums are now handled appropriately. In such
  cases, `albumstatus` gets set to **Promotional**, and the release date will be a future
  date instead of past.

### Fixed

- Handle a sold-out release where the track listing isn't available, which would otherwise
  cause a KeyError.

- Catalogue number parser should now forget that cassette types like **C30** or **C90**
  could be valid catalogue numbers.

### Updated

- Brought dev dependencies up-to-date.

## [0.5.3] 2021-01-19

### Fixed

- For data that is parsed directly from the html, ampersands are now correctly
  unescaped.

## [0.5.2] 2021-01-18

### Fixed

- On Bandcamp merch is listed in the same list together with media - this is now
  taken into account and merch is ignored. Previously, some albums would fail to
  be returned because of this.

## [0.5.1] 2021-01-18

### Fixed

- Fixed readme headings where configuration options were shown in capitals on `PyPI`.

## [0.5.0] 2021-01-18

### Added

- Added some functionality to exclude digital-only tracks for media that aren't
  _Digital Media_. A new configuration option `include_digital_only_tracks`, if
  set to `True` will include all tracks regardless of the media, and if set to
  `False`, will mind, for example, a _Vinyl_ media and exclude tracks that
  have some sort of _digital only_ flag in their names, like `DIGI`, `[Digital Bonus]`,
  `[Digital Only]` and alike. These flags are also cleared from the
  track names.

### Fixed

- For LP Vinyls, the disc count and album type are now corrected.

## [0.4.4] 2021-01-17

### Fixed

- `release_date` search pattern now looks for a specific date format, guarding
  it against similar matches that could be found in the description, thanks
  @noahsager.

## [0.4.3] 2021-01-17

### Fixed

- Handled a `KeyError` that would come up when looking for an album/track where
  the block describing available media isn't found. Thanks @noahsager.

### Changed

- Info logs are now `DEBUG` logs so that they're not printed without the verbose
  mode, thanks @arogl.

## [0.4.2] 2021-01-17

### Fixed

- `catalognum` parser used to parse `Vol.30` or `Christmas 2020` as catalogue
  number - these are now excluded. It's likely that additional patterns will
  come up later.

### Added

- Added the changelog.

## [0.4.1] 2021-01-16

### Fixed

- Fixed installation instructions in the readme.

## [0.4.0] 2021-01-16

### Added

- The pipeline now uses generators, therefore the plug-in searches until it
  finds a good fit and won't continue further (same as the musicbrainz autotagger)
- Extended the parsing functionality with data like catalogue number, label,
  country etc. The full list is given in the readme.
