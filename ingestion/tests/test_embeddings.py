"""Unit tests for the embedding model wrapper.

Mocks SentenceTransformer to avoid downloading the ~2.3GB model in tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _make_mock_model(dim: int = 384) -> MagicMock:
    mock = MagicMock()
    mock.encode.return_value = np.random.rand(3, dim).astype(np.float32)
    mock.get_sentence_embedding_dimension.return_value = dim
    return mock


class TestEmbeddingModelInit:
    def test_model_not_loaded_on_construction(self):
        with patch.dict("sys.modules", {"sentence_transformers": MagicMock()}):
            from pipeline.embeddings import EmbeddingModel

            model = EmbeddingModel(model_name="test-model")
            assert model._model is None

    def test_stores_config(self):
        from pipeline.embeddings import EmbeddingModel

        model = EmbeddingModel(model_name="custom/model", dimension=768, device="cpu")
        assert model._model_name == "custom/model"
        assert model._dimension == 768
        assert model._device == "cpu"


class TestEmbedBatch:
    def test_returns_list_of_float_lists(self):
        mock_st_module = MagicMock()
        mock_model_instance = _make_mock_model()
        mock_st_module.SentenceTransformer.return_value = mock_model_instance

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module}):
            from pipeline.embeddings import EmbeddingModel

            model = EmbeddingModel()
            result = model.embed_batch(["text1", "text2", "text3"])

        assert isinstance(result, list)
        assert len(result) == 3
        for embedding in result:
            assert isinstance(embedding, list)
            assert len(embedding) == 384
            assert all(isinstance(v, float) for v in embedding)

    def test_lazy_loads_model_on_first_call(self):
        mock_st_module = MagicMock()
        mock_model_instance = _make_mock_model()
        mock_st_module.SentenceTransformer.return_value = mock_model_instance

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module}):
            from pipeline.embeddings import EmbeddingModel

            model = EmbeddingModel(model_name="test-model", device="cpu")
            assert model._model is None

            model.embed_batch(["hello"])

            mock_st_module.SentenceTransformer.assert_called_once_with("test-model", device="cpu")
            assert model._model is not None

    def test_does_not_reload_model_on_second_call(self):
        mock_st_module = MagicMock()
        mock_model_instance = _make_mock_model()
        mock_st_module.SentenceTransformer.return_value = mock_model_instance

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module}):
            from pipeline.embeddings import EmbeddingModel

            model = EmbeddingModel()
            model.embed_batch(["first"])
            model.embed_batch(["second"])

            mock_st_module.SentenceTransformer.assert_called_once()

    def test_passes_batch_size_to_encode(self):
        mock_st_module = MagicMock()
        mock_model_instance = _make_mock_model()
        mock_st_module.SentenceTransformer.return_value = mock_model_instance

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module}):
            from pipeline.embeddings import EmbeddingModel

            model = EmbeddingModel()
            texts = ["a", "b", "c"]
            model.embed_batch(texts, batch_size=16)

            mock_model_instance.encode.assert_called_once_with(texts, batch_size=16)


class TestEmbedSingle:
    def test_delegates_to_embed_batch(self):
        mock_st_module = MagicMock()
        mock_model_instance = MagicMock()
        mock_model_instance.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        mock_model_instance.get_sentence_embedding_dimension.return_value = 384
        mock_st_module.SentenceTransformer.return_value = mock_model_instance

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module}):
            from pipeline.embeddings import EmbeddingModel

            model = EmbeddingModel()
            result = model.embed_single("hello world")

            assert isinstance(result, list)
            assert len(result) == 384
            mock_model_instance.encode.assert_called_once_with(["hello world"], batch_size=32)


class TestDimension:
    def test_returns_configured_dimension(self):
        from pipeline.embeddings import EmbeddingModel

        model = EmbeddingModel(dimension=768)
        assert model.dimension == 768

    def test_default_dimension(self):
        from pipeline.embeddings import EmbeddingModel

        model = EmbeddingModel()
        assert model.dimension == 384

    def test_does_not_load_model(self):
        from pipeline.embeddings import EmbeddingModel

        model = EmbeddingModel()
        _ = model.dimension
        assert model._model is None


class TestImportError:
    def test_clear_error_when_sentence_transformers_missing(self):
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            from pipeline.embeddings import EmbeddingModel

            model = EmbeddingModel()
            with pytest.raises(ImportError, match="sentence-transformers is required"):
                model.embed_batch(["test"])
