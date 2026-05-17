from __future__ import annotations

import os
import time

import structlog

logger = structlog.get_logger()

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_DIM = 384


class EmbeddingModel:
    """Wrapper around SentenceTransformer with lazy model loading.

    Reads SSA_EMBEDDING_MODEL and SSA_EMBEDDING_DIM from environment variables.
    The model is only loaded into memory on the first call to embed_batch() or
    embed_single(), not at construction.
    """

    def __init__(
        self,
        model_name: str | None = None,
        dimension: int | None = None,
        device: str | None = None,
    ) -> None:
        self._model_name = model_name or os.environ.get("SSA_EMBEDDING_MODEL", _DEFAULT_MODEL)
        self._dimension = dimension or int(os.environ.get("SSA_EMBEDDING_DIM", str(_DEFAULT_DIM)))
        self._device = device
        self._model = None

    def _load_model(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required. Install with: uv sync --extra embeddings"
            ) from None

        logger.info(
            "loading_embedding_model",
            model_name=self._model_name,
            expected_dim=self._dimension,
            device=self._device,
        )
        start = time.perf_counter()

        self._model = SentenceTransformer(self._model_name, device=self._device)

        actual_dim = self._model.get_sentence_embedding_dimension()
        if actual_dim != self._dimension:
            msg = (
                f"Model {self._model_name} produces {actual_dim}-dim vectors "
                f"but SSA_EMBEDDING_DIM={self._dimension}"
            )
            raise ValueError(msg)

        elapsed = time.perf_counter() - start
        logger.info(
            "embedding_model_loaded",
            model_name=self._model_name,
            dimension=self._dimension,
            elapsed_seconds=round(elapsed, 2),
        )

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        if self._model is None:
            self._load_model()

        logger.info(
            "embedding_batch",
            num_texts=len(texts),
            batch_size=batch_size,
        )
        start = time.perf_counter()

        embeddings = self._model.encode(texts, batch_size=batch_size)

        elapsed = time.perf_counter() - start
        logger.info(
            "embedding_batch_complete",
            num_texts=len(texts),
            elapsed_seconds=round(elapsed, 2),
            texts_per_second=round(len(texts) / elapsed, 1) if elapsed > 0 else 0,
        )

        return [row.tolist() for row in embeddings]

    def embed_single(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    @property
    def dimension(self) -> int:
        return self._dimension
