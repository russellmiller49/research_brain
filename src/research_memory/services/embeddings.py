from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.preprocessing import normalize

PINNED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
PINNED_MODEL_REPOSITORY = "qdrant/bge-small-en-v1.5-onnx-q"
PINNED_MODEL_REVISION = "52398278842ec682c6f32300af41344b1c0b0bb2"
PINNED_MODEL_FILE = "model_optimized.onnx"
PINNED_MODEL_SHA256 = "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"


class Embedder(Protocol):
    backend_name: str
    dimension: int
    warning: str | None

    def encode(self, texts: list[str]) -> np.ndarray: ...


@dataclass
class HashEmbedder:
    """Deterministic offline fallback used until the bundled model is installed."""

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


class FastEmbedder:
    """Pinned quantized ONNX BGE embeddings executed entirely on-device."""

    warning: str | None = None

    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
    ):
        from fastembed import TextEmbedding

        model_path = verified_pinned_model_path(model_name, cache_dir)
        self._model = TextEmbedding(
            model_name=model_name,
            cache_dir=str(cache_dir),
            local_files_only=True,
            specific_model_path=str(model_path),
            threads=2,
        )
        self.dimension = 384
        self.backend_name = f"fastembed:{model_name}:q-onnx"

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        values = list(self._model.embed(texts, batch_size=128, parallel=None))
        vectors = np.asarray(values, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.maximum(norms, 1e-12)


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


def create_embedder(
    backend: str,
    model_name: str,
    model_dir: Path | None = None,
    *,
    allow_download: bool = False,
) -> Embedder:
    if backend == "fastembed":
        try:
            cache_dir = model_dir or Path.home() / ".research-memory" / "models"
            if allow_download:
                return install_fastembed_model(model_name, cache_dir)
            return FastEmbedder(model_name, cache_dir)
        except Exception as exc:
            return HashEmbedder(
                warning=(
                    "The local BGE model is not installed, so Recall Search is using "
                    f"the lexical fallback ({exc.__class__.__name__}). Install the "
                    "offline model in Settings, then run a resumable reindex."
                )
            )
    if backend == "sentence-transformers":
        try:
            return SentenceTransformerEmbedder(model_name)
        except Exception as exc:
            return HashEmbedder(
                warning=(
                    "Sentence-transformer embeddings were unavailable, so the app "
                    f"fell back to the offline hash index ({exc.__class__.__name__})."
                )
            )
    return HashEmbedder()


def install_fastembed_model(model_name: str, model_dir: Path) -> FastEmbedder:
    from huggingface_hub import snapshot_download

    if model_name != PINNED_MODEL_NAME:
        raise ValueError(f"Only the pinned beta model {PINNED_MODEL_NAME} may be installed")
    model_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=PINNED_MODEL_REPOSITORY,
        revision=PINNED_MODEL_REVISION,
        cache_dir=model_dir,
        local_files_only=False,
    )
    embedder = FastEmbedder(model_name, model_dir)
    # Force ONNX/tokenizer load and verify the expected output dimension.
    probe = embedder.encode(["Research Memory model verification"])
    if probe.shape != (1, embedder.dimension):
        raise RuntimeError("The installed embedding model failed verification")
    return embedder


def verified_pinned_model_path(model_name: str, model_dir: Path) -> Path:
    if model_name != PINNED_MODEL_NAME:
        raise ValueError(f"Only the pinned beta model {PINNED_MODEL_NAME} may be loaded")
    snapshot = (
        model_dir
        / f"models--{PINNED_MODEL_REPOSITORY.replace('/', '--')}"
        / "snapshots"
        / PINNED_MODEL_REVISION
    )
    onnx = snapshot / PINNED_MODEL_FILE
    if not onnx.is_file():
        raise FileNotFoundError(f"The pinned model snapshot is not installed at {snapshot}")
    digest = hashlib.sha256()
    with onnx.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    if digest.hexdigest() != PINNED_MODEL_SHA256:
        raise ValueError("The pinned ONNX model failed its SHA-256 integrity check")
    return snapshot


def vector_to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes(order="C")


def blob_to_vector(blob: bytes, dimension: int) -> np.ndarray:
    vector = np.frombuffer(blob, dtype=np.float32, count=dimension)
    return vector.copy()
