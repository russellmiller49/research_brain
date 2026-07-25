from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.preprocessing import normalize


class Embedder(Protocol):
    backend_name: str
    dimension: int
    warning: str | None

    def encode(self, texts: list[str]) -> np.ndarray: ...


@dataclass
class HashEmbedder:
    """Fast, private, deterministic local similarity vectors.

    This baseline uses hashed word and bigram features. It is not a language
    model, but it provides useful approximate-recall behavior with no model
    download and acts as a safe fallback for every installation.
    """

    dimension: int = 512
    warning: str | None = None
    backend_name: str = "hash-v1"

    def __post_init__(self) -> None:
        self._vectorizer = HashingVectorizer(
            n_features=self.dimension,
            alternate_sign=False,
            norm=None,
            stop_words="english",
            ngram_range=(1, 2),
            lowercase=True,
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        sparse = self._vectorizer.transform(texts)
        sparse = normalize(sparse, norm="l2", copy=False)
        return sparse.astype(np.float32).toarray()


class SentenceTransformerEmbedder:
    backend_name: str
    warning: str | None = None

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dimension = int(self._model.get_sentence_embedding_dimension())
        self.backend_name = f"sentence-transformers:{model_name}"

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


def create_embedder(backend: str, model_name: str) -> Embedder:
    if backend == "sentence-transformers":
        try:
            return SentenceTransformerEmbedder(model_name)
        except Exception as exc:  # optional dependency or unavailable local model
            return HashEmbedder(
                warning=(
                    "Sentence-transformer embeddings were unavailable, so the app "
                    f"fell back to the offline hash index ({exc.__class__.__name__})."
                )
            )
    return HashEmbedder()


def vector_to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes(order="C")


def blob_to_vector(blob: bytes, dimension: int) -> np.ndarray:
    vector = np.frombuffer(blob, dtype=np.float32, count=dimension)
    return vector.copy()
