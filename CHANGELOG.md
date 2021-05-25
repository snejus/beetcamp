## [0.8.1] 2021-05-25

### Updated

- Removing `(FREE)`, `(free download)`-like strings from the track names.
- All testcases are now pretty JSON files - this should bring more transparency around
  the adjustments that Bandcamp make in the future (once they get updated).

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
