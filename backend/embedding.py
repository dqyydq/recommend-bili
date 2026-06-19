import asyncio
import hashlib
import os
import re
from functools import lru_cache

import numpy as np
from openai import AsyncOpenAI
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.preprocessing import normalize

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "fastembed").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY", "")
EMBEDDING_CONCURRENCY = int(os.getenv("EMBEDDING_CONCURRENCY", "4"))
HASHING_DIMENSIONS = int(os.getenv("HASHING_EMBEDDING_DIMENSIONS", "384"))
_ACTIVE_COLLECTION_SUFFIX: str | None = None


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return cleaned[:48] or "default"


def embedding_collection_suffix() -> str:
    if _ACTIVE_COLLECTION_SUFFIX:
        return _ACTIVE_COLLECTION_SUFFIX
    return configured_embedding_collection_suffix()


def configured_embedding_collection_suffix() -> str:
    if EMBEDDING_PROVIDER == "hashing":
        return f"hashing_{HASHING_DIMENSIONS}"
    model_hash = hashlib.sha1(EMBEDDING_MODEL.encode("utf-8")).hexdigest()[:8]
    return f"{_slug(EMBEDDING_PROVIDER)}_{model_hash}"


@lru_cache(maxsize=1)
def _fastembed_model():
    from fastembed import TextEmbedding

    cache_dir = os.getenv(
        "FASTEMBED_CACHE_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "fastembed")),
    )
    os.makedirs(cache_dir, exist_ok=True)
    return TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=cache_dir)


def _set_active_suffix(value: str) -> None:
    global _ACTIVE_COLLECTION_SUFFIX
    _ACTIVE_COLLECTION_SUFFIX = value


def _hashing_embeddings(texts: list[str]) -> list[list[float]]:
    vectorizer = HashingVectorizer(
        n_features=HASHING_DIMENSIONS,
        alternate_sign=False,
        norm=None,
        analyzer="char_wb",
        ngram_range=(2, 4),
    )
    matrix = vectorizer.transform(texts)
    matrix = normalize(matrix, norm="l2", copy=False)
    return matrix.astype(np.float32).toarray().tolist()


async def _fastembed_embeddings(texts: list[str]) -> list[list[float]]:
    def run() -> list[list[float]]:
        model = _fastembed_model()
        vectors = model.embed(texts, batch_size=int(os.getenv("FASTEMBED_BATCH_SIZE", "64")))
        return [np.asarray(vector, dtype=np.float32).tolist() for vector in vectors]

    return await asyncio.to_thread(run)


async def _openai_embeddings(texts: list[str]) -> list[list[float]]:
    if not EMBEDDING_API_KEY:
        raise RuntimeError("EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER=openai")

    client = AsyncOpenAI(api_key=EMBEDDING_API_KEY, base_url=EMBEDDING_BASE_URL)
    semaphore = asyncio.Semaphore(EMBEDDING_CONCURRENCY)

    async def embed_batch(batch: list[str]) -> list[list[float]]:
        async with semaphore:
            resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
            ordered = sorted(resp.data, key=lambda item: item.index)
            return [item.embedding for item in ordered]

    batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
    batches = [texts[index:index + batch_size] for index in range(0, len(texts), batch_size)]
    results = await asyncio.gather(*(embed_batch(batch) for batch in batches))
    return [embedding for batch in results for embedding in batch]


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    cleaned = [(text or "").strip() or "empty" for text in texts]
    if not cleaned:
        return []

    if EMBEDDING_PROVIDER == "openai":
        _set_active_suffix(configured_embedding_collection_suffix())
        return await _openai_embeddings(cleaned)
    if EMBEDDING_PROVIDER == "hashing":
        _set_active_suffix(configured_embedding_collection_suffix())
        return _hashing_embeddings(cleaned)

    try:
        embeddings = await _fastembed_embeddings(cleaned)
        _set_active_suffix(configured_embedding_collection_suffix())
        return embeddings
    except Exception as exc:
        print(f"[embedding] fastembed failed, falling back to hashing: {exc}")
        _set_active_suffix(f"hashing_{HASHING_DIMENSIONS}")
        return _hashing_embeddings(cleaned)
