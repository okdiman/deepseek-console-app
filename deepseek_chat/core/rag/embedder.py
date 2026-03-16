"""
Ollama embedding client.

Calls POST /api/embed on a locally running Ollama instance.
Batches texts to avoid oversized requests.
"""

import json
import urllib.error
import urllib.request
from typing import List

from .config import RagConfig

_BATCH_SIZE = 32


class OllamaEmbeddingClient:
    def __init__(self, config: RagConfig) -> None:
        self._config = config

    def health_check(self) -> bool:
        """Return True if Ollama is reachable."""
        try:
            urllib.request.urlopen(
                f"{self._config.ollama_url}/api/tags", timeout=3
            )
            return True
        except Exception:
            return False

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts. Returns a parallel list of float vectors.

        Raises RuntimeError if Ollama is unreachable or returns an error.
        """
        if not texts:
            return []

        results: List[List[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i: i + _BATCH_SIZE]
            results.extend(self._embed_batch(batch))
        return results

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        payload = json.dumps({
            "model": self._config.ollama_model,
            "input": texts,
        }).encode()

        req = urllib.request.Request(
            f"{self._config.ollama_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama not reachable at {self._config.ollama_url}. "
                f"Start it with: ollama serve\n  ({exc})"
            ) from exc

        embeddings = data.get("embeddings")
        if not embeddings:
            raise RuntimeError(
                f"Ollama returned no embeddings. Response: {data}"
            )
        return embeddings
