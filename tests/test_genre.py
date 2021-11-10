import pytest
from beetsplug.bandcamp._metaguru import Metaguru


def test_style(genre_config):
    guru = Metaguru("", genre_config)
    guru.meta = {"publisher": {"genre": "bandcamp.com/tag/folk"}}
    assert guru.style == "folk"


TEST_KEYWORDS = dict(
    single_word_valid_kw=["house"],
    double_word_valid_kw=["tech house"],
    double_word_valid_separately=["techno house"],
    only_last_word_valid=["crazy techno"],
    invalid_kw=["crazy music"],
    no_kw=[],
)


@pytest.fixture(params=TEST_KEYWORDS.keys())
def keyword_type(request):
    return request.param


@pytest.fixture
def keywords(keyword_type):
    return TEST_KEYWORDS[keyword_type]


@pytest.fixture(scope="module")
def modes_spec():
    base_spec = dict(
        single_word_valid_kw=True,
        double_word_valid_kw=True,
        double_word_valid_separately=False,
        only_last_word_valid=False,
        invalid_kw=False,
        no_kw=False,
    )
    modes = {}
    modes["classical"] = base_spec
    modes["progressive"] = {**base_spec, "double_word_valid_separately": True}
    modes["psychedelic"] = {**modes["progressive"], "only_last_word_valid": True}
    return modes


@pytest.fixture(params=["classical", "progressive", "psychedelic"])
def mode(request):
    return request.param


@pytest.fixture
def mode_result(keywords, keyword_type, modes_spec, mode):
    return keywords if modes_spec[mode][keyword_type] else []


def test_genre(keywords, mode, mode_result):
    assert list(Metaguru.get_genre(keywords, mode)) == mode_result


@pytest.mark.parametrize(
    ("capitalize", "maximum", "expected"),
    [
        (True, 0, "Folk, House, Grime, Trance"),
        (True, 3, "Folk, House, Grime"),
        (False, 2, "folk, house"),
    ],
)
def test_genre_config(capitalize, maximum, expected, genre_config):
    meta = {
        "keywords": ["paris", "dubstep", "folk", "House", "grime", "Trance"],
        "publisher": {"genre": "https://bandcamp.com/tag/dubstep"},
    }
    config = genre_config.copy()
    config["genre"].update({"capitalize": capitalize, "maximum": maximum})
    guru = Metaguru("", config)
    guru.meta = meta

    assert guru.style == ("Dubstep" if capitalize else "dubstep")
    assert guru.genre == expected
