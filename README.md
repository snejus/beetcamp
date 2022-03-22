[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner2-direct.svg)](https://vshymanskyy.github.io/StandWithUkraine)

---

[![image](http://img.shields.io/pypi/v/beetcamp.svg)](https://pypi.python.org/pypi/beetcamp)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=snejus_beets-bandcamp&metric=alert_status)](https://sonarcloud.io/dashboard?id=snejus_beets-bandcamp)
[![Coverage Status](https://coveralls.io/repos/github/snejus/beetcamp/badge.svg?branch=master)](https://coveralls.io/github/snejus/beetcamp?branch=master)
[ ![Hits](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2Fsnejus%2Fbeetcamp&count_bg=%23842424&title_bg=%23846060&icon=postwoman.svg&icon_color=%23CF4D4D&title=hits&edge_flat=true)](https://hits.seeyoufarm.com)

Plug-in for [beets] to use Bandcamp as an autotagger source. It mostly focuses on

- Staying up-to-date with information Bandcamp provide in the JSON metadata
- Parsing **all possible** (if relevant) metadata from various places
  - For example, a catalog number given in the release or media description
- Correctness of the data
  - For example, determining artist names from various artists releases
- Compliance with MusicBrainz fields format, to remove the need for pre-processing if, for
  example, one wishes to upload the metadata to MB.

Thanks to [unrblt] for [beets-bandcamp] providing the idea and initial implementation.

[beets]: https://github.com/beetbox/beets
[unrblt]: https://github.com/unrblt
[beets-bandcamp]: https://github.com/unrblt/beets-bandcamp

# Installation

## Recommended method

1. Install `beets` with `pipx` so that it's isolated from your system and other projects

```bash
pipx install beets
```

2. Inject `beetcamp` and other dependencies that you need

```bash
pipx inject beets beetcamp [python-mpd2 ...]
```

3. Add `bandcamp` to the `plugins` list to your beets configuration file.

## Otherwise

Navigate to your `beets` virtual environment and install the plug-in with

```bash
   pip install beetcamp
```

# Configuration

## Default

```yaml
bandcamp:
  preferred_media: Digital Media
  include_digital_only_tracks: true
  search_max: 2
  art: yes
  comments_separator: "\n---\n"
  exclude_extra_fields: []
  genre:
    capitalize: no
    maximum: 0
    always_include: []
    mode: progressive # classical, progressive or psychedelic
```

---

#### `preferred_media`

- Type: **string**
- Default: `Digital Media`

A comma-separated list of media to prioritize when fetching albums. For example:
`preferred_media: Vinyl,Cassette` will ignore `CD`, check for a `Vinyl`, and then for a
`Cassette`, in the end defaulting to `Digital Media` (always available) if none of the two are
found. Any combination of the following is supported: `Vinyl`, `CD`, `Cassette`,
`Digital Media`.

---

#### `include_digital_only_tracks`

- Type: **bool**
- Default: `true`

For media that isn't `Digital Media`, include all tracks, even if their titles contain
**digital only** (or alike).

If you have `False` here, then, for example, a `Vinyl` media of an album will only include
the tracks that are supposed to be found in that media.

---

#### `search_max`

- Type: **int**
- Default: `10`.

Maximum number of items to fetch through search queries. Depending on the specificity of
queries and whether a suitable match is found, it could fetch 50+ results which may take a
minute, so it'd make sense to bound this to some sort of sensible number. Usually, a match
is found among the first 5 items.

---

#### `art`

- Type: **bool**
- Default: `false`.

Add a source to the
[FetchArt](http://beets.readthedocs.org/en/latest/plugins/fetchart.html) plug-in to
download album art for Bandcamp albums (requires `FetchArt` plug-in enabled).

---

#### `comments_separator`

- Type: **string**
- Default: `"\n---\n"`.

The separator that divides release, media descriptions and credits within the `comments`
field. By default you would get

    Description
    ---
    Media description
    ---
    Credits

#### `exclude_extra_fields`

- Type: **list**
- Default: _`empty`_

List of fields that you _do not_ want to see in the metadata. For example, if you find the
inclusion of `comments` irrelevant and are not interested in lyrics, you could specify

```yaml
bandcamp:
  search_max: 5
  exclude_extra_fields:
    - lyrics
    - comments
```

and the plugin will skip them.

You cannot exclude `album`, `album_id`, `artist_id`, `media` and `data_url` album fields.

---

#### `genre` (new since 0.11.0)

- Type: **object**
- Default:
  ```yaml
  genre:
    capitalize: no
    maximum: 0 # no maximum
    mode: progressive
    always_include: []
  ```

**genre.capitalize**: **Classical, Techno** instead of default **classical, techno**.
For consistency, this option also applies to the `style` field.

**genre.maximum** caps the maximum number of included genres. This may be of
value in those cases where artists/labels begin the list with the most relevant keywords,
however be aware it is rarely the case.

**genre.mode** accepts one of the following options: **classical** (less genres) or **progressive** or
**psychedelic** (more genres). Each later one is more flexible regarding what is a valid
genre and what is not. See below (we use the list of [musicbrainz genres] for reference).

**genre.always_include**: genre patterns that override the mode and always match
successfully. For example, if you want to bypass checks for every keyword that ends with
`core`, you could specify

```yaml
genre:
  always_include:
    - "core$"
```

##### `genre` modes

We can place all keywords into the following buckets:

| type  |                                      |                                                                      |
| :---: | ------------------------------------ | -------------------------------------------------------------------- |
| **1** | **`genre`**                          | a valid single-word musicbrainz genre                                |
| **1** | **`more specific genre`**            | a valid musicbrainz genre made of multiple words                     |
| **2** | **`somegenre`** **`someothergenre`** | each of the words is a valid musicbrainz genre, but the combo is not |
| **3** | very specific **`genre`**            | not all words are valid genres, but the very last one is             |
| **4** | maybe **`genre`** but                | but it is followed by noise at the end                               |
| **4** | some sort of location                | irrelevant                                                           |

- **classical** mode strictly follows the musicbrainz list of genres, therefore it covers
  **type 1** only
- **progressive** mode, in addition to the above, takes into account each of the words that
  make up the keyword and will be fine as long as each of those words maps to some sort of
  genre from the musicbrainz list. It covers **types 1 and 2**.
- **psychedelic** (or **noise**) mode, in addition to the above, treats the keyword as a
  valid genre as long as **the last word** in it maps to some genre - covering **types 1 to 3**.
  This one should include the hottest genre naming trends but is also liable to covering the
  latest `<some-label>-<genre>` or `<some-city>-<some-very-generic-genre>` trends which may
  not be ideal. It should though be the best option for those who enjoy detailed, fine-grained
  stats.
- **type 4** is ignored in each case (can be overridden and included through the `genre.include` option).

See below for some examples and a comparison between the modes.

|  type | keyword                 | classical | progressive | psychedelic |
| ----: | ----------------------- | :-------: | :---------: | :---------: |
| **1** | **`techno`**            |     ✔     |      ✔      |      ✔      |
| **1** | **`funk`**              |     ✔     |      ✔      |      ✔      |
| **1** | **`ambient`**           |     ✔     |      ✔      |      ✔      |
| **1** | **`noise`**             |     ✔     |      ✔      |      ✔      |
| **1** | **`ambient techno`**    |     ✔     |      ✔      |      ✔      |
| **2** | **`techno`** **`funk`** |     ✖     |      ✔      |      ✔      |
| **4** | funky                   |     ✖     |      ✖      |      ✖      |
| **4** | bleep                   |     ✖     |      ✖      |      ✖      |
| **3** | funky **`techno`**      |     ✖     |      ✖      |      ✔      |
| **4** | bleepy beep             |     ✖     |      ✖      |      ✖      |
| **3** | bleepy beep **`noise`** |     ✖     |      ✖      |      ✔      |
| **4** | bleepy **`noise`** beep |     ✖     |      ✖      |      ✖      |

# Usage

This plug-in uses Bandcamp release URL as `album_id` (`.../album/...` for albums and
`.../track/...` for singletons). If no matching release is found during the import you can
select `enter Id` and paste the URL that you have.

## Supported metadata

| field          | singleton | album track | album | note                                                                                |
| -------------: | :-------: | :---------: | :---: | :---------------------------------------------------------------------------------: |
| `album`        |           |             | ✔     |                                                                                     |
| `album_id`     |           |             | ✔     | release Bandcamp URL                                                                |
| `albumartist`  |           |             | ✔     |                                                                                     |
| `albumstatus`  |           |             | ✔     |                                                                                     |
| `albumtype`    | \*✔       |             | ✔     |                                                                                     |
| `artist`       | ✔         | ✔           | ✔     |                                                                                     |
| `artist_id`    | ✔         |             | ✔     | label / publisher Bandcamp URL                                                      |
| `catalognum`   | \*✔       |             | ✔     |                                                                                     |
| `comments`     | ✔         | ✔           |       | release and media descriptions, and credits                                         |
| `country`      | \*✔       |             | ✔     |                                                                                     |
| `day`          | \*✔       |             | ✔     |                                                                                     |
| `disctitle`    | \*✔       | ✔           |       |                                                                                     |
| `genre`        | \*✔       |             | ✔     | comma-delimited list of **release keywords** which match [musicbrainz genres]       |
| `index`        |           | ✔           |       |                                                                                     |
| `label`        | \*✔       |             | ✔     |                                                                                     |
| `length`       | ✔         | ✔           |       |                                                                                     |
| `lyrics`       | ✔         | ✔           |       |                                                                                     |
| `media`        | \*✔       | ✔           | ✔     |                                                                                     |
| `medium`       |           | ✔           |       | likely to be inaccurate, since it depends on information in the release description |
| `mediums`      |           |             | ✔     |                                                                                     |
| `medium_index` |           | ✔           |       | for now, same as `index`                                                            |
| `medium_total` |           | ✔           |       | total number of tracks in the release                                               |
| `month`        | \*✔       |             | ✔     |                                                                                     |
| `style`        | \*✔       |             | ✔     | Bandcamp genre tag                                                                  |
| `title`        | ✔         | ✔           |       |                                                                                     |
| `track_alt`    | ✔         | ✔           |       |                                                                                     |
| `track_id`     |           | ✔           |       | track URL                                                                           |
| `va`           |           |             | ✔     |                                                                                     |
| `year`         | \*✔       |             | ✔     |                                                                                     |

**\*** These singleton fields are available if you use `beets` version `1.5` or higher.

[musicbrainz genres]: https://beta.musicbrainz.org/genres
