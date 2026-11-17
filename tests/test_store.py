import json

import pytest

from app.store import MetadataStore, summarize_model


def make_model(model_id=100, version_ids=(201, 202)):
    return {
        "id": model_id,
        "name": "Test LoRA",
        "type": "LORA",
        "creator": {"username": "someone"},
        "tags": ["character"],
        "nsfw": False,
        "nsfwLevel": 1,
        "availability": "Public",
        "stats": {"thumbsUpCount": 5, "downloadCount": 10, "commentCount": 0},
        "description": "<p>hello</p>",
        "modelVersions": [
            {
                "id": vid,
                "name": f"v{i + 1}",
                "baseModel": "SDXL 1.0",
                "trainedWords": ["trigger one", "trigger two"],
                "publishedAt": "2024-01-01T00:00:00Z",
                "images": [
                    {
                        "url": "https://image.civitai.com/xyz/original=true/123.jpeg",
                        "width": 512,
                        "height": 768,
                        "type": "image",
                        "nsfwLevel": 1,
                    }
                ],
                "files": [
                    {
                        "name": "model.safetensors",
                        "sizeKB": 102400,
                        "type": "Model",
                        "hashes": {"SHA256": "abc123"},
                    }
                ],
            }
            for i, vid in enumerate(version_ids)
        ],
    }


@pytest.fixture
def store(tmp_path):
    return MetadataStore(str(tmp_path / "data"))


class TestMetadataStore:
    def test_save_and_get(self, store):
        saved = store.save_model(make_model(), source_url="https://civitai.com/models/100")
        assert saved["_fetchedAt"]
        assert saved["_sourceUrls"] == ["https://civitai.com/models/100"]

        loaded = store.get_model(100)
        assert loaded["name"] == "Test LoRA"
        assert loaded["_linkedVersionId"] is None

    def test_save_merges_source_urls(self, store):
        store.save_model(make_model(), source_url="https://civitai.com/models/100")
        store.save_model(
            make_model(), source_url="https://civitai.com/models/100?modelVersionId=201"
        )
        loaded = store.get_model(100)
        assert len(loaded["_sourceUrls"]) == 2

    def test_delete(self, store):
        store.save_model(make_model(), source_url="x")
        assert store.delete_model(100) is True
        assert store.get_model(100) is None
        assert store.delete_model(100) is False

    def test_list_models_sorted_newest_first(self, store):
        store.save_model(make_model(model_id=1), source_url="a")
        store.save_model(make_model(model_id=2), source_url="b")
        summaries = store.list_models()
        assert [s["id"] for s in summaries] in ([1, 2], [2, 1])
        assert all("name" in s for s in summaries)

    def test_export_all(self, store):
        store.save_model(make_model(model_id=1), source_url="a")
        store.save_model(make_model(model_id=2), source_url="b")
        exported = store.export_all()
        assert exported["exportedAt"]
        assert [m["id"] for m in exported["models"]] == [1, 2]

    def test_token_roundtrip(self, store):
        assert store.get_token() is None
        store.set_token("  secret-token  ")
        assert store.get_token() == "secret-token"
        store.set_token(None)
        assert store.get_token() is None

    def test_on_disk_json_is_valid(self, store):
        store.save_model(make_model(), source_url="x")
        path = store._model_path(100)
        with open(path, "r", encoding="utf-8") as fh:
            json.load(fh)


class TestSummarizeModel:
    def test_summary_fields(self):
        model = make_model()
        model["_linkedVersionId"] = 202
        summary = summarize_model(model)
        assert summary["id"] == 100
        assert summary["name"] == "Test LoRA"
        assert summary["type"] == "LORA"
        assert summary["creator"] == "someone"
        assert summary["baseModels"] == ["SDXL 1.0"]
        assert summary["versionCount"] == 2
        assert summary["linkedVersionId"] == 202
        assert summary["trainedWords"] == ["trigger one", "trigger two"]
        assert summary["pageUrl"] == "https://civitai.com/models/100"
        assert summary["coverImage"]["url"].endswith("123.jpeg")

    def test_summary_without_versions(self):
        model = make_model()
        model["modelVersions"] = []
        summary = summarize_model(model)
        assert summary["trainedWords"] == []
        assert summary["versionCount"] == 0
        assert summary["coverImage"] is None
