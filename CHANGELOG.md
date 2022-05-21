## [0.16.0] Unreleased

### Fixed

* album: When album name contains **Album (Label something)**, the Label is kept in place
  since it immediately follows an opening parenthesis.


## [0.15.0] 2022-05-16

### Added

* search: 
  - you can now search from the command line: 
    ```sh
    beetcamp [ [-alt] QUERY | RELEASE-URL ]
    ```

  - Search is activated with an argument that does not start with **https://**. It queries
    bandcamp with the provided QUERY and returns a JSON list with all search results from
    the first page, sorted by relevancy.

  - Flags **-a**, **-l** and **-t** can be used to search for **album**, **label/artist** or
    **track** specifically. 

  - Run `beetcamp -h` to see more details. Example: searching for anything called **black sands**:

    ```json
    $ beetcamp 'black sands' | jq '.[:2]'
    [
      {
        "type": "album",
        "name": "Black Sands",
        "artist": "Bonobo",
        "date": "2010 March 29",
        "tracks": "12",
        "url": "https://bonobomusic.bandcamp.com/album/black-sands",
        "label": "bonobomusic",
        "similarity": 1
      },
      {
        "type": "album",
        "name": "Black Sands",
        "artist": "Appalachian Terror Unit",
        "date": "2011 August 01",
        "tracks": "4",
        "url": "https://appalachianterrorunit.bandcamp.com/album/black-sands",
        "label": "appalachianterrorunit",
        "similarity": 1
      }
    ]
    ```

### Updated

* search: 
  - if `label` field is available, the plugin now takes it into account when it ranks
    search results. 
  - `albumartist` field is not used to rank **compilations** anymore since some labels use
    label name, some use the list of artists, and others a variation of **Various Artists** - 
    we cannot reliably tell. `label` is used instead.

* `album`: track titles are read to see whether they contain the album name. There are
  cases where titles have the following format: **Title [Album Name EP]**

* `catalognum`: 
  - search track titles
  - do not match if preceded by **]** character
  - allow catalogue numbers like **o-ton 113**
  - allow a pair, if separated by a slash `/`
  - removed a pattern responsible for a fair bit of false positives

* `albumtype`: 
  - to determine whether a release is a compilation, check comments for string
    **compilation**
  - check if all track titles are remixes; if so - include **remix** albumtype into
    `albumtypes`

* `albumtypes`:
  - **remix**: check for string **rmx** in album name
  - **compilation**: even if a release is an **ep**, check whether it's also a compilation
    and include it

### Fixed

* search: fixed searching of singletons, where the plugin now actually performs search instead of 
  immediately returning the currently selected singleton when option **E** was selected
  during the import process

* album art fetching functionality has been broken for a while - it should now work fine

* `album`: simplified album name clean-up logic and thus fixed a couple of edge cases

* `albumartist`: remove **, more** from the end

* `catalognum`: in rare cases, if the track list was given in the comments, one of the
  track titles would get assumed for the catalognum and subsequently cleaned up. From now
  on this will only apply if **all** track names include the match (usually delimited by
  brackets at the end)

* `title`: 
  - track parsing has been refactored, therefore many of previously removed bits from the
    title are now kept in place, such as bits in parentheses, double quotes (unless they
    wrap the entire title) or non-alphanumeric characters at the end
  - allow titles to start with an opening parentheses :exploding_head:
  - when the title is found as **(Some Remix) Title**, it becomes **Title (Some Remix)**

* `artist`: 
  - featuring artists given in square brackets are now parsed correctly
  - de-duplication now ignores the case
  - when only one of the track artists in the release is missing, try splitting the name
    with **-** (no spaces) to account for bad formatting

* `track_alt`: track alts with numbers above 6 (like **A7**) and letters **A** and **B**
  on their own are now extracted successfully

## [0.14.0] 2022-04-18

### Added

* `media`: 
  * previously, we picked the very first **Vinyl**, **CD** etc. media available and the
    rest did not exist from the plugin's point of view. This is now updated: every media
    which maps to tracks in the same release will get returned, similar to Discogs and
    MusicBrainz autotaggers. 

    Therefore, `bandcamp.preferred_media` configuration option does not have any effect
    anymore and it can be safely removed from your configuration. Instead, use the global
    `preferred.media` option and adjust distance weights correspondingly.

  * If **Vinyl** format track list is found in its description, then `track_alt`,
    `medium`, `medium_index` and `medium_total` are adjusted accordingly.


* new field `albumtypes` which contains secondary release types, such as **remix**,
  **live**, **soundtrack** etc. Applies to `beets >= 1.5`

### Updated

* internal: Tests clean up: pytest fixture-spaghetti has been replaced with JSON files that
  contain the expected output data.

* `albumtype`: some accuracy improvements
  * For **Vinyl** media, all `disctitle`s are checked for **EP** or **LP** presence
  * **EP**, **LP** and **album** words in release and media descriptions are counted and decide the album type
  * If **compilation** or **best of** or **anniversary** is present in the album name, then
    the release is a compilation
  * A single album with an original track and several remixes now has **album** albumtype, not **single**

* `albumartist`: every release with more than 3 artists will now have **Various Artists** (or `va_name`) albumartist

### Fixed

* `album`: 
  * Remove **EP** or **LP** from the beginning more reliably
  * Only remove **VA** if album name starts or ends with it

[0.14.0]: https://github.com/snejus/beetcamp/releases/tag/0.14.0

## [0.13.2] 2022-04-03

### Fixed

* Fixed importing of officially purchased Bandcamp tracks which have **Visit {label_url}** in their `COMMENT` field (at least for FLAC files) when the album name does not contain a single ASCII alphanumeric character. We here use the album name to guess the release url, and in this case the plugin has previously been failing to take into account this edge case and failed the import process immediately.

[0.13.2]: https://github.com/snejus/beetcamp/releases/tag/0.13.2

## [0.13.1] 2022-04-03

### Fixed

* search: changes introduced in [0.13.0] broke searching functionality for `python 3.6-3.8` due to changes in the built-in `difflib` library. This has been fixed and tests for the searching logic are now added. Thanks to @emanuele-virgillito for reporting the issue.

[0.13.1]: https://github.com/snejus/beetcamp/releases/tag/0.13.1

## [0.13.0] 2022-03-22

### Added

- search: considerable improvements in search results accuracy

  - Release name and artist is parsed for each found release
  - They are compared to what's being queried and sorted by best matches
  - Therefore, from now on we will check the first search results page only which should
    yield up to 18 results.
  - `search_max` parameter is now **2** by default, - in most cases you should get by fine
    with it being set to **1**. This will make the search nearly instant and reduce the
    loads that Bandcamp need to deal with.

- Python 3.10 is now supported.

### Updated

- `album`

  - search priority: step by step until the first one which is found:

    1. Whatever follows **Title:** in the release **description**
    1. Something in single or double quotes in the release **title**
    1. If **EP** or **LP** is in the release **title**, whatever precedes it having removed `catalognum` and artists
    1. Whatever is left in the release **title** having removed `catalognum` and artists
    1. Whatever precedes **EP** or **LP** string in the release **description**
    1. `catalognum`
    1. The entire initial release **title**

  - remove **(digital album)** and **(album)** from the album name

    ```yaml
    Some Album (album) -> Some Album
    ```

- `label`: strip quotes if sourced from the description

- `artist`/`albumartist`: remove remixers from artists fields
  ```yaml
  title: Choone (Some Remix) -> title: Choone (Some Remix)
  artist: Artist, Some       -> artist: Artist
  ```

- `artist`/`title`: **featuring** artists are moved from `title` to the `artist` field
    ```yaml
    artist: Artist        -> Artist ft. Some
    title: Title ft. Some -> Title
    ```

- `singleton`: do not populate `albumstatus`, `index`, `medium_index`, `medium`,
  `medium_total` fields

### Fixed

- `artist` / `track_alt`: 
  - artists like **B2** and **A4** are not anymore assumed to be `track_alt` when
  `track_alt` is not present in any other track in that release.

  ```yaml
  # name: B2 - Some Title
  title: Some Title -> Some Title
  track_alt: B2     ->
  artist:           -> B2

  ```

  - and other way around, `track_alt` like **A** or **B** are correctly parsed if
    `track_alt` was found for the rest of the tracks

- `catalognum`: catalogue numbers starting with **VA** are not anymore ignored, unless
  **VA** is followed by numbers. **VA02** is still ignored while **VAHELLO001** is now
  parsed correctly.

- Fixed Github workflow which tests the package across various python and `beets` versions: they should now fail reliably. Dependencies are from now on cached, so they run fairly quickly.

- Clarified that `preferred_media` should include **Digital Media** (not **Digital**) in
  the README.

[0.13.0]: https://github.com/snejus/beetcamp/releases/tag/0.13.0

## [0.12.0] 2022-02-10

### Added

- `album`: following MusicBrainz [title format specification], strings **EP** and **LP** are from now on kept in place in album names.
- `catalognum`: To find the catalog number, we have previously been looking at the release title and pointers such as **Catalogue Number:** within the release description.

  In addition to the above, we now apply a generic search pattern across the rest of the text, including media title, media description and the rest of the release description.

  For those interested, at a high level the pattern used in the search looks like below

  ```perl
  (
        [A-Z .]+\d{3}         # HANDS D300
      | [A-z ][ ]0\d{2,3}     # Persephonic Sirens 012
      | [A-Z-]{2,}\d+         # RIV4
      | [A-Z]+[A-Z.$-]+\d{2,} # USE202, HEY-101, LI$025
      | [A-Z.]{2,}[ ]\d{1,3}  # OBS.CUR 9
      | \w+[A-z]0\d+          # 1ØPILLS018, fa036
      | [a-z]+(cd|lp)\d+      # ostgutlp45
      | [A-z]+\d+-\d+         # P90-003
  )
  ( # optionally followed by
        [ ]?[A-Z]     # IBM001V
      | [.][0-9]+     # ISMVA002.1
      | -?[A-Z]+      # PLUS8024CD
  )?
  ```

- `albumtype`: similar to the `catalognum`, the descriptions are searched for **EP** and **LP** strings presence to find out the `albumtype`.

- `track`: Support for tracks that do not use dash (`-`) but some other character to separate pieces of information in track names. For example, consider the following [tracklist]:

  ```
  A1 | WHITESHADOWHURTS x TOXICSPIKEBACK | Arcadia
  A2 | WHITESHADOWHURTS | Corrupted Entity
  A3 | WHITESHADOWHURTS | Colosseo
  B1 | TOXICSPIKEBACK | Eclipse
  B2 | TOXICSPIKEBACK | Eclipse [DJ LINT's Tribe Mix]
  B3 | WHITESHADOWHURTS | Corrupted Entity [OAT.M's Oldschool Mix]
  ```

  `beetcamp` now finds that `|` is being used as the delimiter and parses values for `track_alt`, `artist` and `title` accordingly.

### Updated

- singleton: `album` and `albumartist` fields are not anymore populated.
- `catalognum`: artists like **PROCESS 404** are not assumed to be catalogue numbers anymore.
- `track_alt`: allow non-capital letters, like **a1** to be parsed and convert them to capitals.
- `albumartist`: use **Various Artists** (or equivalent) when a release includes more than four different artists. Until now we've only done so for compilations.
- `genre`: genres are now sorted alphabetically

### Fixed

- Support for `beets<1.5` has been broken since `0.11.0`, - it should now work fine. However, fields such as `comments` and `lyrics` are not available, and album-like metadata like `catalognum` is not available for singletons. Thanks **@zane-schaffer** for reporting this issue (Closes #22).
- `singleton`: `catalognum`, if found, is now reliably removed from the title.
- `track.title`: `-` delimiter is handled more appropriately when it is found in the song title.
- `albumartist`: for the Various Artists releases, the plugin will now use the globally configured `va_name` field instead of hard-coding _Various Artists_.
- `artist`: Recent bandcamp updates of the JSON data removed artists names from most of compilations, therefore we are again having a peek at the raw HTML data to fetch the data from there.

[tracklist]: https://scumcllctv.bandcamp.com/album/scum002-arcadia
[title format specification]: https://beta.musicbrainz.org/doc/Style/Titles
[0.12.0]: https://github.com/snejus/beetcamp/releases/tag/0.12.0

## [0.11.0] 2021-11-12

### Added

- An entrypoint for `beetcamp`: if the package is in your `$PATH`, bandcamp
  metadata can be obtained directly as a JSON

  ```bash
  beetcamp <bandcamp-url>
  # {"album": "some album", ..., "tracks": [{"title": ...}, ... ]}
  ```

  This has mostly been useful in scripts: for example, in my case it bridges the metadata
  gap between mpd and a last.fm scrobbler in those cases when music has not yet made it
  into the beets library.

- Two more MusicBrainz fields now get populated:

  - `style`: the tag/genre that bandcamp categorize the release as
  - `genre`: comma-delimited list of release **keywords** that match any [musicbrainz
    genres].

  This comes with some configuration options, see the defaults below:

  ```yaml
  bandcamp:
    ...
    genre:
      capitalise: no
      maximum: 0  # no limit
      always_include: []
      mode: progressive  # classical, progressive or psychedelic
  ```

  See the readme for information about the different options.

- New configuration option `comments_separator` to separate release, media
  descriptions and credits. Default: `\n---\n`. Comments formatting has been
  changing with every release without a good reason - this should stop. Ultimately it is
  one's personal choice how they want the formatting to look like.

### Updated

- `excluded_extra_fields` configuration option has been extended to support every track
  field and most of album fields. See the readme for more information.

- The hook for additional data has been removed since `lyrics` and `description` are now
  retrieved immediately. They can be inspected like every other field, through, for
  example, the **`edit (C)andidates`** action during the import.

- `track_alt`: allow **B2 Title** where _B2_ is followed by a space
- `catalognum`: include **Catalog:** as a valid header when parsing the description
- `track.title` digital-only cleanup, remove:
  - **DIGITAL** and **Bonus** from the front of the title
  - **digital-only** and **(digital)** from the end

### Fixed

- `lyrics`: instead of parsing the HTML, lyrics are now reliably retrieved from the JSON
  data and added to each track where applicable.
- Nowadays it is possible that the `datePublished` field is not given in the release JSON
  data - this is now handled gracefully.

[musicbrainz genres]: https://beta.musicbrainz.org/genres
[0.11.0]: https://github.com/snejus/beetcamp/releases/tag/0.11.0

## [0.10.1] 2021-09-13

### Fixed

- Fixed #18 by handling cases when a track duration is not given.
- Fixed #19 where artist names like **SUNN O)))** would get incorrectly mistreated by
  the album name cleanup logic due to multiple consecutive parentheses. The fix involved
  adding some rules around it: they are now deduplicated _only if_

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
  asterisks

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

- Added a github action to run CI for `master` and `dev` branches. For now it's just a minimal
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
- `album.catalognum`: Make the _DISCTITLE_ uppercase before looking for the catalog
  number.
- `album.media`: Exclude anything that contains _bundle_ in their names. These usually
  contain additional releases that we do not need.
- `track.title`: Clean `- DIGITAL ONLY` (and similar) when it's preceded by a dash and not
  enclosed by parentheses or square brackets.
- `track.track_alt`: Having witnessed a very creative track title **E7-E5**, limit the
  `track_alt` field number to the range **0-6**.
- Committed a JSON test case which was supposed to be part of `0.9.0`.

### Added

- Extend `url2json` with `--tracklist-for-tests` to ease adding new test cases.

## [0.9.0] 2021-06-01

### Fixed

- If track artist is given in the `byArtist` field of the track JSON resource, it is used.
  (Fixes #13, thanks @xeroxcat).
- Parse cases like `Catalogue:CAT-000` from the description correctly when the space is missing.

### Added

- The `comments` field now includes the media description and credits.
- The description is searched for artist and album names in addition to the catalog
  number.

### Updated

- All test cases are now pretty JSON files - this should bring more transparency around
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

  - Token `feat.` is now recognized as a valid member of the `artist` field.
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

- Release description is now checked for the catalog number.
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
  - Catalog number
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
- Sped up re-importing bandcamp items by checking whether the URL is already available
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

- Catalog number parser now requires at least two digits to find a good match.

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

- Catalog number parser should now forget that cassette types like **C30** or **C90**
  could be valid catalog numbers.

### Updated

- Brought dev dependencies up-to-date.

## [0.5.3] 2021-01-19

### Fixed

- For data that is parsed directly from the html, ampersands are now correctly unescaped.

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

- `catalognum` parser used to parse `Vol.30` or `Christmas 2020` as catalog
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
- Extended the parsing functionality with data like catalog number, label,
  country etc. The full list is given in the readme.
