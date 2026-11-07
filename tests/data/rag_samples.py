"""RAG 테스트용 표본 레코드와 가짜 임베더 (test_rag_chunks.py·test_rag_index.py 공용)."""

import hashlib


def welfare_rec(serv_id="WLF00004828", source="local", scope="district", ctpv="대구광역시", sgg="남구", **kw):
    rec = {
        "serv_id": serv_id, "source": source, "scope": scope, "ctpv": ctpv, "sgg": sgg,
        "name": "경로우대사업", "summary": "65세 이상 어르신 이미용 50% 할인",
        "target_detail": "65세 이상 노인", "selection_criteria": "65세 이상 노인",
        "benefits": "경로우대업소 영업자에게 월 보상금 지급", "apply_detail": "지정 업소에 방문",
        "apply_methods": ["방문"], "apply_guides": [], "support_cycle": "분기", "provision_types": ["현금지급"],
        "contacts": [{"name": "남구청 복지지원과", "value": "053-664-2538", "raw": {}}],
        "department": "대구광역시 남구 복지지원과", "ministry": None, "main_contact": None,
        "detail_url": "https://www.bokjiro.go.kr/x", "detail_fetched_at": "2026-11-05T00:00:00+00:00",
        "source_fetched_at": "2026-11-05T15:20:26+00:00", "last_modified": "2026-03-01",
        "period_end": "9999-12-31", "unverified_fields": [], "quality_flags": [],
        "raw_sha256": hashlib.sha256(f"welfare:{serv_id}".encode()).hexdigest(),
    }
    rec.update(kw)
    return rec


def recipe_rec(recipe_id="28", status="ok", allergens=("대두", "알류"), suspect=False, **kw):
    rec = {
        "recipe_id": recipe_id, "name": "새우 두부 계란찜", "category": "반찬", "cooking_method": "찌기",
        "hashtag": "연두부", "ingredients_text": "연두부 75g(3/4모), 달걀 30g(1/2개)\n고명\n시금치 10g",
        "steps": [{"no": 1, "text": "새우를 데친다."}, {"no": 2, "text": "찜기에 10분 찐다."}],
        "missing_step_nos": [], "sodium_tip": "새우 간으로 맛을 내요.",
        "nutrition": {"energy_kcal": 220.0, "carbohydrate_g": 3.0, "protein_g": 14.0, "fat_g": 17.0,
                      "sodium_mg": 99.0, "suspect": suspect},
        "allergens": {"detected": [{"allergen": a, "kind": "direct"} for a in allergens]},
        "quality": {"status": status,
                    "issues": [{"code": "ingredient_amount_missing"}] if status == "flagged" else []},
        "source": {"fetched_at": "2026-10-31T16:29:00+00:00",
                   "raw_sha256": hashlib.sha256(f"recipe:{recipe_id}".encode()).hexdigest()},
    }
    rec.update(kw)
    return rec


def payloads(benefits="월 보상금 지급"):
    """대구 남구 사업·전국 사업·대구시 전체 사업·부산 남구 사업·끝난 사업 + 레시피 2개."""
    welfare = {"input": {"local": {"sha256": "aaa"}, "central": {"sha256": "bbb"}},
               "records": [welfare_rec(benefits=benefits),
                           welfare_rec("WLF00001164", "central", "national", None, None, name="기초연금",
                                       summary="노인에게 매달 연금 지급", benefits=benefits),
                           welfare_rec("WLF9", ctpv="부산광역시", name="부산 남구 사업", benefits=benefits),
                           welfare_rec("WLF8", scope="province", sgg=None, name="대구 식사배달",
                                       summary="결식 우려 어르신 도시락 배달", benefits=benefits),
                           welfare_rec("WLF7", name="끝난 사업", period_end="2020-01-01", benefits=benefits)]}
    recipes = {"input": {"sha256": "ccc"},
               "records": [recipe_rec("28"),
                           recipe_rec("397", allergens=(), name="호박죽", ingredients_text="단호박 200g, 찹쌀가루 30g")]}
    return welfare, recipes


class FakeEmbedder:
    """글자 bigram을 고정 해시로 64차원에 모은 정규화 벡터. 같은 글 = 같은 벡터(실행마다 같음)."""

    def __init__(self, model_id="fake@1", dim=64):
        self.model_id, self.dim, self.calls = model_id, dim, 0

    def _vec(self, text):
        import numpy as np

        v = np.zeros(self.dim, dtype=np.float32)
        s = text.replace(" ", "")
        for i in range(len(s) - 1):
            h = int.from_bytes(hashlib.md5(s[i:i + 2].encode()).digest()[:4], "little")
            v[h % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_passages(self, texts, show_progress=False):
        import numpy as np

        self.calls += len(texts)
        return np.vstack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def embed_query(self, text):
        return self._vec(text)
