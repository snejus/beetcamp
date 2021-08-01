[![image](http://img.shields.io/pypi/v/beetcamp.svg)](https://pypi.python.org/pypi/beetcamp)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=snejus_beets-bandcamp&metric=alert_status)](https://sonarcloud.io/dashboard?id=snejus_beets-bandcamp)

Plug-in for [beets](https://github.com/beetbox/beets) to use Bandcamp as
an autotagger source.

This is an up-to-date fork of [unrblt/beets-bandcamp](https://github.com/unrblt/beets-bandcamp)

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
and add `bandcamp` to the `plugins` list to your beets configuration file.

## Otherwise

Navigate to your `beets` virtual environment and install the plug-in with

```bash
   pip install beetcamp
```


# Configuration

## Example

```yaml
bandcamp:
    preferred_media: Vinyl,CD,Cassette
    include_digital_only_tracks: true
    search_max: 5
    art: true
    exclude_extra_fields:
      - lyrics
      - comments
```

---

#### `preferred_media`

- Type: **string**
- Default: `Digital`

A comma-separated list of media to prioritise when fetching albums. For example:
`preferred_media: Vinyl,Cassette` will ignore `CD`, check for a `Vinyl`, and then for a
`Cassette`, in the end defaulting to `Digital` (always available) if none of the two are
found. Any combination of the following is supported: `Vinyl`, `CD`, `Cassette`,
`Digital`.

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

#### `exclude_extra_fields`

- Type: **list**
- Default: _`empty`_

The data that is added **after** the core auto tagging process is considered extra:
(currently) `lyrics` and `comments` (release description) fields (see [the data
table](#currently-supported--returned-data) for the complete list). Since there yet isn't
an easy way to preview them before they get applied, you can ignore them if you find them
irrelevant or inaccurate.

For example, if you wanted to ignore all the goodies you can specify
```yaml
bandcamp:
    search_max: 5
    exclude_extra_fields:
      - lyrics
      - comments
```

# Usage

This plug-in uses the Bandcamp URL as id (for both albums and songs). If no matching
release is found when importing you can select `enter Id` and paste the Bandcamp URL.

## Currently supported / returned data

| field            | is extra | singleton track | album track | album |
|-----------------:|:--------:|:---------------:|:-----------:|:-----:|
| `album`          |          | ✔~              |             | ✔     |
| `album_id`       |          |                 |             | ✔     |
| `albumartist`    |          | ✔               | ✔           | ✔     |
| `albumstatus`    |          | ✔~              |             | ✔     |
| `albumtype`      |          | ✔~              |             | ✔     |
| `artist`         |          | ✔               | ✔           | ✔     |
| `artist_id`      |          | ✔               | ✔           |       |
| `catalognum`     |          | ✔~              |             | ✔     |
| + `comments`     | ✔        | ✔               | ✔           |       |
| `country`        |          | ✔~              |             | ✔     |
| `day`            |          | ✔~              |             | ✔     |
| `disctitle`      |          | ✔~              | ✔           |       |
| `image`          |          | ✔               | ✔           | ✔     |
| `index`          |          | ✔               | ✔           |       |
| `label`          |          | ✔~              | ✔           | ✔     |
| `length`         |          | ✔               | ✔           |       |
| `lyrics`         | ✔        | ✔               | ✔           |       |
| `media`          |          | ✔~              | ✔           | ✔     |
| `medium`         |          | ✔~              | ✔           |       |
| `mediums`        |          |                 |             | ✔     |
| * `medium_index` |          | ✔~              | ✔           |       |
| * `medium_total` |          | ✔~              | ✔           |       |
| `month`          |          | ✔~              |             | ✔     |
| `title`          |          | ✔               | ✔           |       |
| `track_alt`      |          | ✔               | ✔           |       |
| `va`             |          |                 |             | ✔     |
| `year`           |          | ✔~              |             | ✔     |

**\+** `comments` field gets populated with the release description.

**\*** are likely to be inaccurate, since Bandcamp does not provide this data,
  therefore they depend on artists providing some clues in the descriptions of
  their releases. This is only relevant if you have `per_disc_numbering` set to
  `True` in the global beets configuration.

**\~** These singleton fields are available if you use `beets` version `1.5` or higher.
