"""KURE-v1 임베딩 (docs/data/rag_embedding_decision.md 1절).

- 원본 fp32 가중치 그대로 쓴다(경량화·양자화 안 함).
- 질문·문서에 접두어를 붙이지 않는다. 벡터는 길이 1로 정규화 → 내적 = 코사인 유사도.
- 설치: uv sync --extra embed (torch CPU 전용판). 모델은 첫 실행 때 Hugging Face 캐시로 받는다(약 2.3GB).
"""

from __future__ import annotations

from typing import Protocol

MODEL_NAME = "nlpai-lab/KURE-v1"
MODEL_REVISION = "8b418a58414668e75532ed045c22d9ca018ae2b2"   # 2026-09-07
MODEL_ID = f"{MODEL_NAME}@{MODEL_REVISION}"
DIM = 1024


class Embedder(Protocol):
    model_id: str
    dim: int

    def embed_passages(self, texts: list[str], show_progress: bool = False): ...   # (n, dim) float32
    def embed_query(self, text: str): ...                                        # (dim,) float32


class KureEmbedder:
    model_id = MODEL_ID
    dim = DIM

    def __init__(self, device: str = "cpu", batch_size: int = 16, threads: int | None = None):
        self.device, self.batch_size, self.threads = device, batch_size, threads
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                import torch
                from sentence_transformers import SentenceTransformer
            except ImportError as e:  # pragma: no cover - 설치 안내
                raise RuntimeError("임베딩 모델은 `uv sync --extra embed` 후 사용하세요.") from e
            if self.threads:
                torch.set_num_threads(self.threads)
            self._model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device=self.device)
            get_dim = getattr(self._model, "get_embedding_dimension", None) \
                or self._model.get_sentence_embedding_dimension      # sentence-transformers 6 이전 이름
            dim = get_dim()
            if dim != DIM:
                raise RuntimeError(f"{MODEL_ID} 차원이 {dim} — 예상 {DIM}")
        return self._model

    def _encode(self, texts: list[str], show_progress: bool):
        import numpy as np

        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        v = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                              convert_to_numpy=True, show_progress_bar=show_progress)
        return np.asarray(v, dtype=np.float32)

    def embed_passages(self, texts: list[str], show_progress: bool = False):
        return self._encode(list(texts), show_progress)

    def embed_query(self, text: str):
        return self._encode([text], False)[0]
