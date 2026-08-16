import math
import re
from collections import Counter


def tokenize(text: str) -> list[str]:
    """Tokenize CJK characters plus latin words, then add CJK bigrams."""
    lowered = text.lower()
    tokens = re.findall(r"[\u4e00-\u9fff]|[a-z]+|\d+", lowered)
    cjk = [token for token in tokens if re.fullmatch(r"[\u4e00-\u9fff]", token)]
    bigrams = [a + b for a, b in zip(cjk, cjk[1:], strict=False)]
    return tokens + bigrams


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a.get(key, 0.0) * b.get(key, 0.0) for key in a.keys() | b.keys())
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class TfidfIndex:
    """A small, deterministic TF-IDF + cosine-similarity retriever."""

    def __init__(self, documents: list[str]) -> None:
        self.documents = documents
        self._tokenized = [tokenize(document) for document in documents]
        self._document_frequency: dict[str, int] = {}
        for tokens in self._tokenized:
            for term in set(tokens):
                self._document_frequency[term] = (
                    self._document_frequency.get(term, 0) + 1
                )
        self._count = len(documents)
        self._vectors = [self._vector(tokens) for tokens in self._tokenized]

    def _vector(self, tokens: list[str]) -> dict[str, float]:
        frequencies = Counter(tokens)
        vector: dict[str, float] = {}
        for term, freq in frequencies.items():
            idf = math.log(
                (self._count + 1) / (self._document_frequency.get(term, 0) + 1)
            ) + 1
            vector[term] = freq * idf
        return vector

    def search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        query_vector = self._vector(tokenize(query))
        scored = [
            (index, _cosine(query_vector, vector))
            for index, vector in enumerate(self._vectors)
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [(index, score) for index, score in scored[:top_k] if score > 0]
