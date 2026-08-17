"""Chunking and the local deterministic embedding used to ground retrieval.

This SaaS ships without a paid embeddings provider wired in — Anthropic's Messages API has
no embeddings endpoint of its own; Anthropic's own docs point customers at a separate
provider (Voyage AI) for that. Rather than bolt on a second paid, network-dependent
provider for a feature this project needs to build and test without live API keys, chunk
vectors here are a deterministic, dependency-free hashed bag-of-words (a signed
feature-hashing scheme, the same idea behind scikit-learn's `HashingVectorizer`): the same
text always embeds to the same vector, and two texts sharing vocabulary land closer
together under cosine distance. That is enough to exercise the real pgvector storage,
index, and retrieval path end-to-end. Swapping in a real embeddings API means replacing
`embed_text()` below — nothing else in this app depends on how the vector was produced.
See PHASES.md "Not built in Phase 8" for the explicit call-out.
"""

from __future__ import annotations

import hashlib
import math
import re

#: Kept modest — this is a hashed bag-of-words, not a learned embedding, so a larger
#: dimension buys nothing but a bigger index.
EMBEDDING_DIMENSIONS = 256

#: Words per chunk, and how many trail into the next chunk so a fact sitting on a
#: boundary is never split away from its surrounding sentence.
CHUNK_SIZE_WORDS = 220
CHUNK_OVERLAP_WORDS = 40

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def embed_text(text: str) -> list[float]:
    """A deterministic, dependency-free stand-in for a real embeddings API call."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    words = _WORD_RE.findall(text.lower())
    if not words:
        vector[0] = 1.0
        return vector

    for word in words:
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign

    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [component / norm for component in vector]


def chunk_text(
    text: str, *, size: int = CHUNK_SIZE_WORDS, overlap: int = CHUNK_OVERLAP_WORDS
) -> list[str]:
    """Split into overlapping fixed-size word windows so no fact straddles a boundary."""
    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [" ".join(words)]

    chunks: list[str] = []
    step = max(size - overlap, 1)
    start = 0
    while start < len(words):
        chunks.append(" ".join(words[start : start + size]))
        if start + size >= len(words):
            break
        start += step
    return chunks
