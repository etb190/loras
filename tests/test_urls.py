import pytest

from app.urls import parse_civitai_link, split_links


class TestParseCivitaiLink:
    def test_plain_model_url(self):
        link = parse_civitai_link("https://civitai.com/models/12345")
        assert link.model_id == 12345
        assert link.version_id is None
        assert not link.is_empty

    def test_model_url_with_slug(self):
        link = parse_civitai_link("https://civitai.com/models/12345/awesome-lora-v2")
        assert link.model_id == 12345
        assert link.version_id is None

    def test_model_url_with_version_query(self):
        link = parse_civitai_link(
            "https://civitai.com/models/12345/some-slug?modelVersionId=99999"
        )
        assert link.model_id == 12345
        assert link.version_id == 99999

    def test_model_version_url(self):
        link = parse_civitai_link("https://civitai.com/model-versions/777")
        assert link.model_id is None
        assert link.version_id == 777

    @pytest.mark.parametrize("host", ["civitai.red", "civitai.green", "www.civitai.com"])
    def test_supported_hosts(self, host):
        link = parse_civitai_link(f"https://{host}/models/42")
        assert link.model_id == 42

    def test_www_prefix(self):
        link = parse_civitai_link("https://www.civitai.com/models/42")
        assert link.model_id == 42

    def test_scheme_less_url(self):
        link = parse_civitai_link("civitai.com/models/42")
        assert link.model_id == 42

    def test_bare_model_id(self):
        link = parse_civitai_link("12345")
        assert link.model_id == 12345
        assert link.version_id is None

    def test_model_version_shorthand(self):
        link = parse_civitai_link("12345/99999")
        assert link.model_id == 12345
        assert link.version_id == 99999

    def test_trailing_slash(self):
        link = parse_civitai_link("https://civitai.com/models/12345/")
        assert link.model_id == 12345

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "not a link",
            "https://example.com/models/123",
            "https://civitai.com/images/999",
            "https://civitai.com/models/abc",
            "ftp://civitai.com/models/123",
        ],
    )
    def test_unrecognized_input(self, raw):
        assert parse_civitai_link(raw).is_empty


class TestSplitLinks:
    def test_newline_separated(self):
        assert split_links("https://civitai.com/models/1\nhttps://civitai.com/models/2") == [
            "https://civitai.com/models/1",
            "https://civitai.com/models/2",
        ]

    def test_comma_and_space_separated(self):
        assert split_links("https://civitai.com/models/1, 12345 model-versions/77") == [
            "https://civitai.com/models/1",
            "12345",
            "model-versions/77",
        ]

    def test_quotes_stripped(self):
        assert split_links('"https://civitai.com/models/1"') == ["https://civitai.com/models/1"]

    def test_empty(self):
        assert split_links("") == []
        assert split_links("   ") == []
