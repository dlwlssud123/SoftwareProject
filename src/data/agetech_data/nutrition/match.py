"""재료명·음식명 → 식품영양성분DB 식품코드 매핑.

재료 매핑 상태 (영양 계산에 쓰는지)
- reviewed  : 사람이 확인한 수동 매핑 (매핑표에 확인자·확인일)        → 사용
- curated   : 근거를 적은 수동 매핑, 사람 확인 전 (리뷰에서 확인 필요)  → 사용, 보고서에 '검토 대기'
- exact     : 아래 규칙으로 후보가 정확히 1개일 때만                   → 사용
- water     : 물 — 영양 계산에서 0 으로 취급                          → 계산 불필요
- excluded  : 먹지 않거나(건져 내는 월계수잎·국물 우리는 약재) 같은 레시피에서 이미 계산된 재료
              — 매핑표 "exclude" 로 정함, 0 으로 취급하고 완전 판정에서 뺀다 → 계산 불필요
- candidate : 유사 후보만 있음 (검토 목록)                            → 사용 안 함
- unmapped  : 후보 없음 / 매핑표에서 '매핑하지 않음'(DB에 없음 등)    → 사용 안 함 (빠진 재료로 표시)

exact 규칙 (원재료성 식품명은 "상위, 세부, 상태" 쉼표 계층 구조)
- full     : 식품명 전체 = 재료명 (예: 참기름)
- raw      : "재료명, 생것" (예: 양파, 생것)
- variety  : "상위, 재료명[, 생것]" (예: 파, 대파, 생것 / 두부, 순두부)
- alias    : "X(재료명)[, 생것]" 괄호 별칭 (예: 큰느타리버섯(새송이버섯), 생것)
- 다진     : "다진 ○○" 은 "○○, 다진것" 을 먼저 찾고, 없으면 ○○ 로 위 규칙 적용
같은 규칙 안에서 후보가 둘 이상이면 원재료성을 우선하고, 그래도 여럿이면 exact 로 보지 않는다.

손질 표기 (모양만 바뀌고 영양은 같음 — 매핑표에 그 이름이 따로 없을 때)
- "○○다진것"·"○○갈은것" 은 "다진 ○○" 과, "○○채썬것"·"○○작게자른것"·"○○채친것" 은 "○○" 과 같게 찾는다
  (규칙 이름 앞에 "손질+"). 데친것·삶은것·말린것처럼 상태가 바뀌는 표기는 해당하지 않는다.
- "다진 ○○" 은 DB에 "○○, 다진것" 이 따로 없고 매핑표에 "○○" 이 있으면 그 결정을 따른다(규칙 "다진+manual").
  매핑표의 '다진 소고기'·'다진 홍고추'·'양파다진것' 항목이 모두 기본 재료와 같게 정한 것과 같은 기준이다.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Literal

from agetech_data.textutil import nfc

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
INGREDIENT_MAP_FILE = RESOURCES / "ingredient_food_map.json"
DISH_ALIAS_FILE = RESOURCES / "dish_aliases.json"

MatchStatus = Literal["reviewed", "curated", "exact", "water", "excluded", "candidate", "unmapped"]
USABLE: tuple[MatchStatus, ...] = ("reviewed", "curated", "exact")
NOT_COUNTED: tuple[MatchStatus, ...] = ("water", "excluded")   # 0 으로 취급, 완전 판정·무게 비율에서 뺌
# 매핑표 "exclude" 값: 먹지 않음 / 같은 레시피에서 이미 계산 / 영양이 거의 없음(DB에 없는 무열량 감미료 등)
EXCLUDE_REASONS = ("not_eaten", "counted_elsewhere", "negligible")
# 쌀뜨물: DB 항목 없음, 영양 미미 → 물로 취급. 얼음 = 언 물
WATER_NAMES = {"물", "끓는물", "생수", "정수", "쌀뜨물", "얼음", "얼음물", "찬물", "냉수", "온수", "미지근한물", "뜨거운물",
               "따뜻한물", "물미지근한것", "각얼음", "물필요량", "재료물"}
RAW_STATE = "생것"
INGREDIENT_GROUPS = ("원재료성", "가공식품")
GROUP_RANK = {"원재료성": 0, "가공식품": 1, "음식": 2}


def norm(s: str | None) -> str:
    return re.sub(r"\s+", "", nfc(s or "")).lower()


def _get(obj, key):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key)


@dataclass
class FoodRef:
    food_code: str
    name: str
    db_group: str | None
    basis_unit: str | None
    ref_name: str | None
    tokens: list[str]                 # 쉼표 계층을 정규화한 토큰

    @classmethod
    def of(cls, food) -> FoodRef:
        name = _get(food, "name")
        return cls(_get(food, "food_code"), name, _get(food, "db_group"), _get(food, "basis_unit"),
                   _get(food, "ref_name"), [norm(t) for t in name.split(",") if t.strip()])


@dataclass
class MatchResult:
    status: MatchStatus
    food_code: str | None = None
    food_name: str | None = None
    rule: str | None = None
    rationale: str | None = None
    candidates: list[dict] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.status in USABLE

    def to_dict(self) -> dict:
        return asdict(self)


class FoodIndex:
    def __init__(self, foods, groups: tuple[str, ...] = INGREDIENT_GROUPS):
        self.refs = [FoodRef.of(f) for f in foods if _get(f, "db_group") in groups and _get(f, "name")]
        self.by_code = {r.food_code: r for r in self.refs}
        self.by_full: dict[str, list[FoodRef]] = {}
        for r in self.refs:
            self.by_full.setdefault("".join(r.tokens), []).append(r)

    # --- exact 규칙 -------------------------------------------------------
    @staticmethod
    def _pick(cands: list[FoodRef]) -> FoodRef | None:
        if not cands:
            return None
        best = min(GROUP_RANK.get(c.db_group, 9) for c in cands)
        top = [c for c in cands if GROUP_RANK.get(c.db_group, 9) == best]
        return top[0] if len(top) == 1 else None

    def _rules(self, key: str) -> list[tuple[str, list[FoodRef]]]:
        alias = re.compile(rf"^[^()]+\({re.escape(key)}\)$")
        return [
            ("full", self.by_full.get(key, [])),
            ("raw", [r for r in self.refs if r.tokens == [key, RAW_STATE]]),
            # 상위 이름이 재료명에 들어 있을 때만 (파, 대파 O / 샌드위치, 닭고기 X)
            ("variety", [r for r in self.refs if len(r.tokens) >= 2 and r.tokens[1] == key
                         and r.tokens[0] in key and r.tokens[2:] in ([], [RAW_STATE])]),
            ("alias", [r for r in self.refs if any(
                alias.match(t) and r.tokens[i + 1:] in ([], [RAW_STATE])
                for i, t in enumerate(r.tokens[:2]))]),
        ]

    def _raw_family(self, key: str) -> bool:
        """'key, …' / '상위, key, …' / 'X(key), …' 형태의 원재료성 식품이 있는가."""
        tag = f"({key})"
        return any(r.db_group == "원재료성" and (r.tokens[0] == key or r.tokens[0].endswith(tag)
                                                or r.tokens[1:2] == [key] or r.tokens[1:2] and r.tokens[1].endswith(tag))
                   for r in self.refs if r.tokens)

    def _resolve(self, key: str, prefix: str = "") -> tuple[FoodRef, str] | None:
        hits = [(rule, self._pick(c)) for rule, c in self._rules(key)]
        hits = [(rule, h) for rule, h in hits if h]
        raw = [(rule, h) for rule, h in hits if h.db_group == "원재료성"]
        if raw:
            return raw[0][1], prefix + raw[0][0]
        # 가공식품으로만 맞았는데 같은 이름의 원재료 계열이 따로 있으면 자동 확정하지 않는다 (예: 땅콩)
        if hits and not self._raw_family(key):
            return hits[0][1], prefix + hits[0][0]
        return None

    def chopped(self, base: str) -> FoodRef | None:
        """DB에 따로 있는 "○○, 다진것" 항목."""
        key = norm(base)
        return self._pick([r for r in self.refs if r.tokens == [key, "다진것"]])

    def exact(self, name: str) -> tuple[FoodRef, str] | None:
        key = norm(name)
        if not key:
            return None
        if key.startswith("다진") and len(key) > 2:
            base = key[2:]
            chopped = self.chopped(base)
            if chopped:
                return chopped, "다진+state"
            return self._resolve(base, "다진+")
        return self._resolve(key)

    # --- 후보 ------------------------------------------------------------
    def candidates(self, name: str, limit: int = 5, min_score: float = 0.5) -> list[dict]:
        key = norm(name)
        if key.startswith("다진") and len(key) > 2:
            key = key[2:]
        scored = []
        ratios: dict[str, float] = {}          # 같은 첫 이름(돼지고기 …)이 많아 이름별로 한 번만 계산
        chars = set(key)
        for r in self.refs:
            head = r.tokens[0] if r.tokens else ""
            if head not in ratios:
                # 겹치는 글자가 없으면 유사도는 정확히 0 (빈 문자열끼리는 1 이라 그대로 계산)
                ratios[head] = (0.0 if key and head and chars.isdisjoint(head)
                                else SequenceMatcher(None, key, head).ratio())
            s = ratios[head]
            if key and (key in r.tokens or any(key in t for t in r.tokens[:2])):
                s = max(s, 0.8)
            elif head and len(head) >= 2 and head in key:
                s = max(s, 0.6 + 0.3 * len(head) / len(key))
            if RAW_STATE in r.tokens:
                s += 0.05
            if r.db_group == "가공식품":
                s -= 0.05
            if s >= min_score:
                scored.append((round(min(s, 1.0), 3), r))
        scored.sort(key=lambda x: (-x[0], GROUP_RANK.get(x[1].db_group, 9), len(x[1].name), x[1].food_code))
        return [{"food_code": r.food_code, "name": r.name, "db_group": r.db_group, "score": s}
                for s, r in scored[:limit]]


# --- 수동 매핑표 ----------------------------------------------------------
@lru_cache
def load_ingredient_map(path: Path = INGREDIENT_MAP_FILE) -> tuple[dict, ...]:
    if not path.is_file():
        return ()
    return tuple(json.loads(path.read_text(encoding="utf-8"))["entries"])


def _manual(name: str, paren_texts: list[str], entries) -> dict | None:
    key = norm(name)
    hits = [e for e in entries if norm(e["ingredient"]) == key]
    joined = " ".join(paren_texts or [])
    with_paren = [e for e in hits if e.get("when_paren") and e["when_paren"] in joined]
    if with_paren:
        return with_paren[0]
    plain = [e for e in hits if not e.get("when_paren")]
    return plain[0] if plain else None


_SUFFIX_CHOPPED = re.compile(r"^(?P<base>.+?)\s*(?:다진|갈은)\s*것$")
_SUFFIX_CUT = re.compile(
    r"^(?P<base>.+?)\s*(?:(?:(?:채|송송|어슷|깍둑|곱게|얇게|굵게|잘게|작게)\s*)?(?:썬|자른)|채\s*친)\s*것$")
# 앞에 붙인 손질 표기 (띄어 쓴 것만): "간 양파"·"갈은 마늘" → "다진 ○○", "송송 썬 붉은 고추"·"부순 참깨"·
# "굵은 고춧가루"·"깐 마늘" → "○○" (입자 크기·모양·껍질만 다름)
_PREFIX_CHOPPED = re.compile(r"^(?:(?:곱게|굵게|잘게)\s*)?(?:간|갈은|다진)\s+(?P<base>\S.*)$")
_PREFIX_CUT = re.compile(
    r"^(?:(?:(?:송송|어슷|채|곱게|잘게|굵게|얇게|납작|납작하게|깍둑|큼직하게|길게|둥글게|먹기 좋게)\s*)?(?:썬|썰은|자른)|"
    r"부순|깐|껍질 깐|굵은|고운|씻은|손질한|손질된)\s+(?P<base>\S.*)$")
# 앞에 붙인 상태 표기 → DB 의 "○○, 삶은것" 같은 이름 그대로 항목이 있을 때만 (상태가 바뀌면 영양이 달라짐)
_PREFIX_STATE = re.compile(r"^(?P<state>삶은|볶은|마른|말린|데친|구운|찐|불린|익힌)\s*(?P<base>\S.*)$")
_STATE_TOKEN = {"삶은": "삶은것", "볶은": "볶은것", "마른": "말린것", "말린": "말린것", "데친": "데친것",
                "구운": "구운것", "찐": "찐것", "불린": "불린것", "익힌": "익힌것"}
# 뒤에 붙인 상태 표기 "타임마른것"·"당면불린것"·"무청시래기 불린 것" → "마른 타임"·"불린 당면" 순서로 본다
_SUFFIX_STATE = re.compile(r"^(?P<base>.+?)\s*(?P<state>마른|말린|삶은|불린|데친|볶은|찐|구운|익힌)\s*것$")
# 물을 더하거나 익히기만 한 상태 — DB 에 그 상태 항목이 없으면 기본 재료의 매핑으로 근사한다 (말린 것은 제외)
_MILD_STATES = ("삶은", "데친", "찐", "구운", "볶은", "불린", "익힌")
_COOKED_TOKENS = ("삶은것", "데친것", "불린것", "찐것")


def _dried_food(food_name: str) -> bool:
    """'병아리콩, 말린것'·'대두, 콩가루'처럼 마른 상태로 끝나는 식품 (뒤에 '삶은것'이 붙으면 아님).
    이런 식품에 '불린·삶은'을 그대로 대면 물 무게까지 마른 영양으로 쳐서 2~3배로 커진다."""
    toks = [norm(t) for t in food_name.split(",")]
    dried = max((i for i, t in enumerate(toks) if t == "말린것" or t.endswith("가루") or "건조" in t), default=-1)
    cooked = max((i for i, t in enumerate(toks) if t in _COOKED_TOKENS), default=-1)
    return dried > cooked


def prep_alias(name: str) -> str | None:
    """손질 표기만 다른 이름: '양파다진것'·'쇠고기갈은것' → '다진 양파'·'다진 쇠고기', '양파채썬것' → '양파'."""
    n = nfc(name or "").strip()
    m = _SUFFIX_CHOPPED.match(n)
    if m:
        return "다진 " + m.group("base").strip()
    m = _SUFFIX_CUT.match(n)
    if m:
        return m.group("base").strip()
    m = _PREFIX_CHOPPED.match(n)
    if m and not n.startswith("다진"):   # '다진 ○○' 자체는 그대로 (다진+ 규칙이 맡음)
        return "다진 " + m.group("base").strip()
    m = _PREFIX_CUT.match(n)
    return m.group("base").strip() if m else None


# 끝말이 이런 말이면 앞말이 뒷말을 꾸미는 합성어라("쌀 국수"·"들깨 가루"·"고추 기름") 끝말만 떼어 쓰지 않는다
_HEAD_NOUNS = ("국수", "면", "가루", "분말", "기름", "오일", "즙", "주스", "물", "육수", "소스", "장", "청", "잼", "떡",
               "빵", "죽", "차", "술", "식초", "액", "원액", "칩", "튀김", "볶음", "구이", "조림", "무침", "전", "살", "알",
               "잎", "순", "껍질", "뿌리", "줄기", "다리", "몸통", "밑동", "머리", "꼬리", "날개", "가슴", "뼈")


# 앞말이 이런 말로 끝나면 구획·용도 이름("돼지고기 밑간", "청국장소스", "볶음밥", "달래무침")으로 본다
_SECTION_ENDINGS = ("밑간", "양념", "양념장", "소스", "드레싱", "반죽", "고명", "장식", "토핑", "시럽", "재료", "속재료",
                    "밥", "곁들임", "마리네이드", "절임물", "피클물", "육수", "국물", "무침", "볶음", "조림", "구이",
                    "찜", "샐러드", "강된장", "볶음고추장")


def _last_word(name: str) -> str | None:
    """앞말이 구획·용도 이름인 띄어 쓴 이름의 뒷말('돼지고기 밑간 간장' → '간장', '주먹밥 데친 꼬막살' → '데친 꼬막살').
    구획 이름 뒤의 번호는 떼고 본다('소스1 발사믹식초'). 색·상태·품종 같은 꾸밈말('노란색 파프리카'·'검은 콩')은
    구획 이름이 아니라서 해당하지 않는다. 바로 앞말이 구획 이름이 아니면 끝말이 '국수'·'가루' 같은 머리말일 때
    합성어('쌀 국수')로 보고 떼지 않는다."""
    words = nfc(name or "").split()
    if len(words) < 2:
        return None
    marks = [i for i, w in enumerate(words[:-1]) if re.sub(r"\d+$", "", w).endswith(_SECTION_ENDINGS)]
    if not marks:
        return None
    rest = words[marks[-1] + 1:]
    if len(rest) == 1 and rest[0] in _HEAD_NOUNS and marks[-1] != len(words) - 2:
        return None
    return " ".join(rest)


# 이름에 섞여 든 번호·따옴표·분량·크기("소금①", "\"배추", "- 육수", "버터10g", "두부1.2cm", "사과작은것")
_NAME_NOISE = re.compile(r"^[\"'\-\s]+|[①-⑳]+$|\s*\d+(?:\.\d+)?\s*(?:g|ml|cm|인치)?$|"
                         r"(?<=\S)\s*(?:작은|큰|중간|중간크기)\s*것$")


def tidy_name(name: str) -> str:
    """번호·따옴표·붙어 버린 분량을 뗀 재료명 (바뀐 게 없으면 그대로)."""
    n = nfc(name or "").strip()
    while True:
        m = _NAME_NOISE.sub("", n).strip()
        if m == n or not m:
            return n
        n = m


def state_food(name: str, index: FoodIndex) -> FoodRef | None:
    """앞에 붙인 상태 표기 '삶은 달걀'·'볶은 땅콩' → DB 에 이름 그대로 있는 '달걀, 삶은것' 항목(하나일 때만).
    상태가 바뀌면 영양이 달라지므로 기본 재료의 매핑을 따르지 않는다."""
    m = _PREFIX_STATE.match(nfc(name or "").strip())
    if not m:
        return None
    return index._pick(index.by_full.get(norm(m.group("base")) + _STATE_TOKEN[m.group("state")], []))


def manual_entry(name: str, paren_texts: list[str], entries) -> dict | None:
    """이 재료명의 매핑을 정한 매핑표 항목 — 이름 그대로, 손질 표기를 푼 이름, '다진 ○○' 의 ○○ 순서.
    match_ingredient 가 매핑표 결정을 쓴 경우(규칙이 manual 로 끝남)의 확인자·확인일을 찾을 때 쓴다."""
    e = _manual(name, paren_texts, entries)
    if e:
        return e
    tidy = tidy_name(name)
    if tidy != nfc(name or "").strip():
        return manual_entry(tidy, paren_texts, entries)
    alias = prep_alias(name)
    if alias:
        return manual_entry(alias, paren_texts, entries)
    key = norm(name)
    if key.startswith("다진") and len(key) > 2:
        e = _manual(key[2:], paren_texts, entries)
        if e:
            return e
    n = nfc(name or "").strip()
    m = _SUFFIX_STATE.match(n)
    if m:
        return manual_entry(f"{m.group('state')} {m.group('base').strip()}", paren_texts, entries)
    m = _PREFIX_STATE.match(n)
    if m and m.group("state") in _MILD_STATES:
        e = manual_entry(m.group("base"), paren_texts, entries)
        if e:
            return e
    last = _last_word(name)
    return manual_entry(last, paren_texts, entries) if last else None


def _from_manual(e: dict, index: FoodIndex, rule: str = "manual", note: str = "") -> MatchResult:
    rationale = note + (e.get("rationale") or "")
    if e.get("exclude"):  # 먹지 않거나 이미 계산됨 — 0 으로 취급
        if e["exclude"] not in EXCLUDE_REASONS or e.get("food_code") is not None:
            raise ValueError(f"매핑표 exclude 항목이 잘못됨: {e['ingredient']} ({e['exclude']})")
        return MatchResult("excluded", rule=f"{rule}:{e['exclude']}", rationale=rationale)
    if e.get("food_code") is None:  # 매핑하지 않기로 한 결정 (예: 대응 식품 없음)
        return MatchResult("unmapped", rule=f"{rule}:no_match", rationale=rationale)
    ref = index.by_code.get(e["food_code"])
    if ref is None:
        return MatchResult("unmapped", rule=f"{rule}:missing_code",
                           rationale=f"매핑표의 식품코드 {e['food_code']} 가 수집본에 없음")
    status: MatchStatus = "reviewed" if e.get("reviewed_by") else "curated"
    return MatchResult(status, ref.food_code, ref.name, rule, rationale)


def match_ingredient(name: str, index: FoodIndex, paren_texts: list[str] | None = None,
                     entries=None) -> MatchResult:
    """레시피 재료명(괄호 제외 이름) → 매핑 결과. 수동 매핑표가 규칙보다 우선한다."""
    entries = load_ingredient_map() if entries is None else entries
    e = _manual(name, paren_texts or [], entries)
    if e:
        return _from_manual(e, index)
    if norm(name) in WATER_NAMES:
        return MatchResult("water", rule="water", rationale="물은 영양 계산에서 0으로 취급")
    tidy = tidy_name(name)
    if tidy != nfc(name or "").strip():   # "소금①" → "소금"
        r = match_ingredient(tidy, index, paren_texts, entries)
        r.rule = f"정리+{r.rule}" if r.rule else r.rule
        if r.usable or r.status in NOT_COUNTED:
            r.rationale = f"'{name}' = '{tidy}' (번호·기호·분량을 뗌). " + (r.rationale or "")
        return r
    hit = index.exact(name)
    if hit and hit[1] in ("full", "다진+state"):   # DB에 이 이름 그대로인 식품(예: '마늘, 다진것')이 먼저
        return MatchResult("exact", hit[0].food_code, hit[0].name, hit[1], f"규칙 {hit[1]}: 후보 1개")
    sref = state_food(name, index)
    if sref:   # "삶은 달걀" → "달걀, 삶은것"
        return MatchResult("exact", sref.food_code, sref.name, "상태+state", f"'{name}' → DB '{sref.name}'(상태 표기 그대로)")
    alias = prep_alias(name)
    if alias:   # "양파다진것" → "다진 양파" 로 같은 순서를 밟는다. 못 찾으면 원래 이름으로 계속
        r = match_ingredient(alias, index, paren_texts, entries)
        if r.usable or r.status in NOT_COUNTED:
            r.rule = f"손질+{r.rule}"
            r.rationale = f"'{name}' = '{alias}' (손질 표기만 다름). " + (r.rationale or "")
            return r
    key = norm(name)
    if key.startswith("다진") and len(key) > 2 and index.chopped(key[2:]) is None:
        base_entry = _manual(key[2:], paren_texts or [], entries)
        if base_entry and base_entry.get("food_code"):
            return _from_manual(base_entry, index, "다진+manual",
                                f"다진 것 = '{base_entry['ingredient']}' 매핑표 결정과 같음. ")
    if hit:
        ref, rule = hit
        return MatchResult("exact", ref.food_code, ref.name, rule, f"규칙 {rule}: 후보 1개")
    m = _SUFFIX_STATE.match(nfc(name or "").strip())
    if m:   # "타임마른것" → "마른 타임"
        front = f"{m.group('state')} {m.group('base').strip()}"
        r = match_ingredient(front, index, paren_texts, entries)
        if r.usable or r.status in NOT_COUNTED:
            r.rule = f"어순+{r.rule}"
            r.rationale = f"'{name}' = '{front}' (상태 표기 위치만 다름). " + (r.rationale or "")
            return r
    m = _PREFIX_STATE.match(nfc(name or "").strip())
    if m and m.group("state") in _MILD_STATES:   # "삶은 감자" → DB 에 '감자, 삶은것' 이 없으면 '감자' 매핑으로 근사
        r = match_ingredient(m.group("base"), index, paren_texts, entries)
        if r.usable and not _dried_food(r.food_name or ""):
            r.rule = f"상태근사+{r.rule}"
            r.rationale = (f"'{name}': DB 에 '{m.group('state')}' 상태 항목이 없어 '{m.group('base')}' 매핑으로 근사"
                           "(물·익힘에 따른 차이는 작게 봄). " + (r.rationale or ""))
            return r
    last = _last_word(name)
    if last:   # "돼지고기 밑간 간장"·"청국장소스 양송이버섯": 앞말은 구획·용도 이름
        r = match_ingredient(last, index, paren_texts, entries)
        if r.usable:
            r.rule = f"끝말+{r.rule}"
            r.rationale = f"'{name}'의 끝말 '{last}'(앞말은 구획·용도 이름으로 봄). " + (r.rationale or "")
            return r
    cands = index.candidates(name)
    return MatchResult("candidate" if cands else "unmapped", candidates=cands)


# --- 음식명 (사진 분석 등) ------------------------------------------------
# 후보가 어떻게 찾아졌는지 (화면에서 '확인 필요' 정도를 정할 때 쓴다)
#   alias_code : 별칭표가 식품코드를 직접 지정 (예: 배추김치 → 원재료성 '김치, 배추 김치')
#   name       : 음식명 일치 (대표_세부 순서를 바꾼 이름 포함)
#   family     : 대표 음식명만 일치 — 세부 종류 확인 필요 (예: 순두부찌개 → 순두부찌개_김치)
#   partial    : 이름 일부·유사 일치
#   ingredient : 음식 DB군에 맞는 이름이 없어 원재료성 식품에서 찾음 (예: 사과 → 사과, 생것)
#   category   : 이름이 너무 넓어 종류를 골라야 함 (예: 떡 → 가래떡·백설기·절편…). 별칭표 broad 목록 순서대로
FAMILY_SCORE = 0.9
RAW_FALLBACK_MIN = 0.8


@lru_cache
def load_dish_aliases(path: Path = DISH_ALIAS_FILE) -> dict[str, dict]:
    """정규화한 별칭 → {name?, food_code?}. name 은 검색할 음식명, food_code 는 직접 지정할 식품."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {norm(a["alias"]): {k: a[k] for k in ("name", "food_code") if a.get(k)} for a in data["aliases"]}


@lru_cache
def load_broad_names(path: Path = DISH_ALIAS_FILE) -> dict[str, dict]:
    """정규화한 넓은 이름 → {ask, choices}. choices 는 자주 먹는 종류의 음식명(검색어)이다."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {norm(n): {"ask": b["ask"], "choices": b["choices"]} for b in data.get("broad", []) for n in b["names"]}


def dish_choice_question(query: str, aliases: dict | None = None, broad: dict | None = None) -> str | None:
    """넓은 이름이면 화면에 띄울 질문 (예: '어떤 떡인가요?'), 아니면 None."""
    broad = load_broad_names() if broad is None else broad
    q, code = normalize_dish_query(query, aliases)
    b = None if code else broad.get(q)
    return b["ask"] if b else None


def normalize_dish_query(query: str, aliases: dict | None = None) -> tuple[str, str | None]:
    """(검색어, 별칭표가 지정한 식품코드). 별칭 → 이름 치환 뒤 '계란'을 '달걀'로 바꾼다."""
    aliases = load_dish_aliases() if aliases is None else aliases
    q = norm(query)
    a = aliases.get(q)
    code = None
    # 별칭의 name 은 DB 음식명 그대로 적는다('갈비찜_고춧가루'). 검색 키는 '_'를 뺀 형태라 맞춰 준다
    if isinstance(a, str):
        q = norm(a).replace("_", "")
    elif isinstance(a, dict):
        q, code = norm(a.get("name") or q).replace("_", ""), a.get("food_code")
    return q.replace("계란", "달걀"), code


def _dish_keys(r: FoodRef) -> dict[str, float]:
    """음식 식품명 '국밥_돼지머리' → {국밥돼지머리: 1.0, 돼지머리국밥: 0.95, 국밥(대표식품명): 0.7}."""
    keys = {norm(r.name).replace("_", ""): 1.0}
    parts = [norm(p) for p in r.name.split("_") if p.strip()]
    if len(parts) == 2:
        keys.setdefault(parts[1] + parts[0], 0.95)
    if r.ref_name:
        keys.setdefault(norm(r.ref_name), 0.7)
    return keys


def _dish_score(q: str, r: FoodRef) -> tuple[float, str]:
    best = 0.0
    for k, w in _dish_keys(r).items():
        if q == k:
            s = w
        elif len(q) >= 2 and (q in k or k in q):
            s = 0.5 + 0.3 * min(len(q), len(k)) / max(len(q), len(k))
        else:
            s = 0.7 * SequenceMatcher(None, q, k).ratio()
        best = max(best, s * (1 if w >= 0.95 else w / 0.7 * 0.85))
    if best >= 0.95:
        return best, "name"
    # '대표_세부' 이름의 대표 부분이 검색어와 같으면 같은 음식의 세부 종류다.
    # (순두부찌개 → 순두부찌개_김치 가 '두부찌개'보다 앞에 와야 한다)
    if "_" in r.name and norm(r.name.split("_")[0]) == q and best < FAMILY_SCORE:
        return FAMILY_SCORE, "family"
    return best, "partial"


def _raw_fallback(q: str, raw_index: FoodIndex, limit: int) -> list[dict]:
    """음식 DB군에 맞는 이름이 없을 때 원재료성 후보. 같은 점수면 '생것'을 앞에 둔다(사진 속 과일 등)."""
    cands = raw_index.candidates(q, limit=limit * 4, min_score=RAW_FALLBACK_MIN)
    cands = [c for c in cands if c["db_group"] == "원재료성"]
    if len(q) == 1:
        # 한 글자는 부분 일치가 너무 넓다 (떡 → 떡조개, 전 → 전어). 첫 토큰이 같을 때만 (귤 → 귤, 온주밀감, 생것)
        cands = [c for c in cands if norm(c["name"].split(",")[0]) == q]
    cands.sort(key=lambda c: (-c["score"], RAW_STATE not in c["name"].split(", "), len(c["name"]), c["food_code"]))
    return cands[:limit]


def _rank_dishes(q: str, refs: list[FoodRef], skip_code: str | None = None) -> list[tuple[float, str, FoodRef]]:
    scored = []
    for r in refs:
        if r.food_code == skip_code:
            continue
        s, how = _dish_score(q, r)
        if s >= 0.5:
            scored.append((round(s, 3), how, r))
    # 음식명 일치(0.95 이상, 이름 순서만 바뀐 '무국_소고기' 포함)끼리는 100g 기준 행을 먼저 둔다
    scored.sort(key=lambda x: (-1.0 if x[0] >= 0.95 else -x[0], x[2].basis_unit != "g", -x[0], x[2].food_code))
    return scored


def search_dishes(query: str, foods, limit: int = 5, aliases: dict | None = None,
                  raw_index: FoodIndex | None = None, broad: dict | None = None) -> list[dict]:
    """음식명 → 식품 후보 목록. 확정은 사용자·서버가 한다.

    - 기본은 DB군 '음식'에서 찾는다. 점수가 같으면 100g 기준 행을 앞에 둔다.
    - raw_index(원재료성 FoodIndex)를 주면, 별칭표가 지정한 원재료성 식품코드와
      음식명 일치(0.95 이상)가 없을 때의 원재료성 후보를 함께 돌려준다.
    - 넓은 이름(떡·전·생선구이 등, 별칭표 broad)이면 종류마다 대표 행 하나씩을 `category`로 돌려준다.
      이때는 limit 와 상관없이 종류를 모두 돌려준다(화면에서 고르게 함). 질문 문구는 dish_choice_question().
    """
    q, code = normalize_dish_query(query, aliases)
    if not q:
        return []
    refs = foods.refs if isinstance(foods, FoodIndex) else FoodIndex(foods, ("음식",)).refs
    b = None if code else (load_broad_names() if broad is None else broad).get(q)
    if b:
        picks = []
        for choice in b["choices"]:
            # 선택지는 DB 음식명 그대로 적는다 ('수육_소고기'). 검색 키는 '_'를 뺀 형태라 맞춰 준다
            ranked = _rank_dishes(normalize_dish_query(choice, {})[0].replace("_", ""), refs)
            if ranked and ranked[0][1] in ("name", "family"):
                picks.append(_candidate(ranked[0][2], ranked[0][0], "category"))
        if picks:  # 수집본이 바뀌어 종류를 하나도 못 찾으면 일반 검색으로 넘어간다
            return picks
    out: list[dict] = []
    pinned = None
    if code:
        pinned = next((r for r in refs if r.food_code == code), None)
        if pinned is None and raw_index is not None:
            pinned = raw_index.by_code.get(code)
        if pinned is not None:
            out.append(_candidate(pinned, 1.0, "alias_code"))
    dishes = [_candidate(r, s, how) for s, how, r in _rank_dishes(q, refs, pinned.food_code if pinned else None)]
    if raw_index is not None and pinned is None and not (dishes and dishes[0]["score"] >= 0.95):
        raws = [_candidate(raw_index.by_code[c["food_code"]], c["score"], "ingredient")
                for c in _raw_fallback(q, raw_index, limit)]
        # 두 점수 체계가 달라 섞어 정렬하지 않는다. 원재료성 이름 토큰이 검색어와 같을 때(사과 → 사과, 생것)만
        # 음식 후보보다 앞에 두고, 나머지 원재료성 후보는 음식 후보 뒤에 붙인다(불고기 → 소불고기 먼저).
        strong = [c for c in raws if c["score"] >= 0.95]
        dishes = strong + dishes + [c for c in raws if c["score"] < 0.95]
    return (out + dishes)[:limit]


def _candidate(r: FoodRef, score: float, how: str) -> dict:
    return {"food_code": r.food_code, "name": r.name, "db_group": r.db_group, "basis_unit": r.basis_unit,
            "score": score, "match": how}
