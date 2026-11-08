"""BM25 retrieval over the pilot corpus (dense retrieval optional, behind a flag).

Corpus = every .txt/.md file under the corpus dir, chunked on blank lines and
merged to ~800 chars. Pure-stdlib Okapi BM25 so laptop runs need no extras.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Chunk:
    doc_id: str
    chunk_id: int
    text: str


def load_corpus(corpus_dir: str | Path, max_chunk_chars: int = 800) -> list[Chunk]:
    chunks: list[Chunk] = []
    files = sorted(
        p for p in Path(corpus_dir).rglob("*") if p.suffix in (".txt", ".md")
    )
    if not files:
        raise FileNotFoundError(f"no .txt/.md files under {corpus_dir}")
    for path in files:
        paras = [p.strip() for p in path.read_text(encoding="utf-8").split("\n\n") if p.strip()]
        buf = ""
        idx = 0
        for para in paras:
            if buf and len(buf) + len(para) > max_chunk_chars:
                chunks.append(Chunk(path.name, idx, buf))
                idx, buf = idx + 1, para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
        if buf:
            chunks.append(Chunk(path.name, idx, buf))
    return chunks


class BM25Retriever:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self._tf: list[Counter[str]] = [Counter(tokenize(c.text)) for c in chunks]
        self._doc_len = [sum(tf.values()) for tf in self._tf]
        self._avg_len = sum(self._doc_len) / max(len(self._doc_len), 1)
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {
            t: math.log((n - d + 0.5) / (d + 0.5) + 1.0) for t, d in df.items()
        }

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        q_tokens = tokenize(query)
        scores = []
        for i, tf in enumerate(self._tf):
            s = 0.0
            for t in q_tokens:
                if t not in tf:
                    continue
                idf = self._idf.get(t, 0.0)
                norm = tf[t] * (self.k1 + 1) / (
                    tf[t] + self.k1 * (1 - self.b + self.b * self._doc_len[i] / self._avg_len)
                )
                s += idf * norm
            scores.append((s, i))
        scores.sort(key=lambda x: (-x[0], x[1]))
        return [
            {
                "doc_id": self.chunks[i].doc_id,
                "chunk_id": self.chunks[i].chunk_id,
                "score": round(s, 4),
                "text": self.chunks[i].text,
            }
            for s, i in scores[:top_k]
            if s > 0
        ]


class HybridRetriever(BM25Retriever):
    """BM25 + multilingual dense embeddings (requires sentence-transformers)."""

    def __init__(self, chunks: list[Chunk], dense_model: str, **kw):
        super().__init__(chunks, **kw)
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "dense retrieval enabled in config but sentence-transformers is "
                "not installed; set retrieval.dense: false or pip install it"
            ) from e
        self._encoder = SentenceTransformer(dense_model)
        self._embs = self._encoder.encode(
            [c.text for c in chunks], normalize_embeddings=True
        )

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        bm25 = {(r["doc_id"], r["chunk_id"]): r["score"] for r in super().search(query, top_k * 3)}
        q = self._encoder.encode([query], normalize_embeddings=True)[0]
        sims = self._embs @ q
        max_bm25 = max(bm25.values(), default=1.0) or 1.0
        scored = []
        for i, c in enumerate(self.chunks):
            hybrid = 0.5 * (bm25.get((c.doc_id, c.chunk_id), 0.0) / max_bm25) + 0.5 * float(sims[i])
            scored.append((hybrid, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [
            {
                "doc_id": self.chunks[i].doc_id,
                "chunk_id": self.chunks[i].chunk_id,
                "score": round(s, 4),
                "text": self.chunks[i].text,
            }
            for s, i in scored[:top_k]
        ]


def get_retriever(corpus_dir: str | Path, dense: bool = False,
                  dense_model: str = "intfloat/multilingual-e5-small") -> BM25Retriever:
    chunks = load_corpus(corpus_dir)
    return HybridRetriever(chunks, dense_model) if dense else BM25Retriever(chunks)
