"""재료 원문(RCP_PARTS_DTLS) 보존형 파서와 형식 이상 검출.

원칙
- 재료명·분량·괄호 설명을 지우거나 고치지 않는다. 각 항목은 원문 조각 `raw_item` 을 그대로 갖고,
  `raw_item` 을 분할 위치 한 곳에서 `name_raw` / `amount_text` 로 나눈다
  (항상 `raw_item == name_raw + 사이 공백 + amount_text`).
- 숫자·단위(`amount`, `unit`)는 참고용 보조 필드다. 동의어·분류·알레르기 매핑은 식품 매핑 작업에서 한다.

지원하는 원문 형식(실데이터 기준)
  A  연두부 75g(3/4모)            이름 뒤 분량, 괄호는 보조 분량
  B  돼지고기(50g)                분량이 괄호 안
  C  닭고기(가슴살, 120g)          괄호 안에 설명+분량
  Q  참깨 약간                     정성 분량
  섹션: "●양념장 : …", "•육수 : …", "재료 닭가슴살(60g)…"(콜론 없음), 메뉴명·소제목 줄
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Literal

from agetech_data.recipes.issues import Issue
from agetech_data.textutil import clean_text, is_blank, nfc, parse_number

UNITS = [
    "kg", "mg", "g", "ml", "mL", "cc", "L", "cm",
    "큰술", "작은술", "스푼", "숟가락", "티스푼", "컵", "종이컵",
    "개", "알", "모", "장", "잎", "줄기", "뿌리", "대", "쪽", "톨", "마리", "토막", "조각", "송이",
    "봉지", "봉", "팩", "캔", "통", "줌", "꼬집", "포기", "공기", "가닥",
]
QUALITATIVE = ["약간", "적당량", "적당히", "조금", "소량", "넉넉히", "기호에 따라", "취향껏", "한꼬집"]
# 콜론 없이 줄 머리에 오는 섹션 이름 (예: "재료 닭가슴살(60g), …", "육수 다시마(5g)")
INLINE_SECTION_WORDS = [
    "필수 재료", "필수재료", "주재료", "부재료", "재료", "양념장", "양념", "육수", "다시마육수",
    "고기완자양념", "완자", "소스", "드레싱", "장식", "고명", "곁들임",
]

_FRAC = "½⅓⅔¼¾⅕"
_NUM = rf"(?:\d+(?:\.\d+)?(?:\s*/\s*\d+)?[{_FRAC}]?|[{_FRAC}])"
_UNIT = "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True))
_AMOUNT_RE = re.compile(rf"(?P<num>{_NUM})\s*(?P<unit>{_UNIT})?")
_QUAL_RE = re.compile("|".join(map(re.escape, QUALITATIVE)))
_BULLET_RE = re.compile(r"^[●•·▶■◆□○◎※★☆▣►]\s*")
_SERVING_RE = re.compile(r"^\[[^\]]*인분[^\]]*\]\s*")
_INLINE_SECTION_RE = re.compile(
    r"^(?P<sec>" + "|".join(map(re.escape, sorted(INLINE_SECTION_WORDS, key=len, reverse=True)))
    + r")\s+(?=\S)"
)

AmountKind = Literal["measured", "qualitative", "none"]
AmountFormat = Literal["name_amount", "paren_amount", "qualitative", "none"]


@dataclass
class Ingredient:
    order_no: int
    line_no: int                 # 원문 줄 번호(1부터)
    section: str                 # 직전 섹션 제목 원문 (없으면 "")
    raw_item: str                # 원문 조각 그대로
    name_raw: str                # 분할 위치 앞 (설명 괄호 포함, 예: "황태(채)")
    amount_text: str             # 분할 위치 뒤 (예: "15g(10개)", "(50g)", "약간")
    paren_texts: list[str]       # 항목 안 괄호 내용 전부(원문 순서)
    amount_kind: AmountKind
    amount_format: AmountFormat
    amount: float | None = None  # 참고용
    unit: str | None = None      # 참고용

    @property
    def name(self) -> str:
        """괄호를 뺀 이름 (검색·매핑 후보용). 원문은 name_raw."""
        return re.sub(r"\s+", " ", re.sub(r"\([^()]*\)?", " ", self.name_raw)).strip()


@dataclass
class Section:
    line_no: int
    raw_line: str
    title: str
    style: Literal["colon", "inline_word", "title_line"]


@dataclass
class IngredientResult:
    ingredients: list[Ingredient]
    sections: list[Section]
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ingredients": [{**asdict(i), "name": i.name} for i in self.ingredients],
            "ingredient_sections": [asdict(s) for s in self.sections],
        }


def _split_top_level(line: str) -> tuple[list[tuple[int, str]], list[int]]:
    """괄호 밖 쉼표로 분리. ([(원문 시작 위치, 조각)], 쉼표 바로 뒤 공백 없는 위치들)."""
    parts, start, depth, tight = [], 0, 0, []
    for idx, ch in enumerate(line):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch in ",，" and depth == 0:
            parts.append((start, line[start:idx]))
            start = idx + 1
            if start < len(line) and not line[start].isspace():
                tight.append(idx)
    parts.append((start, line[start:]))
    return parts, tight


def _paren_scan(item: str) -> tuple[list[tuple[int, int, str]], bool, bool]:
    """최상위 괄호 [(시작, 끝, 내용)], 미닫힘 여부, 짝 없는 닫힘 여부. 미닫힘이면 끝까지를 내용으로."""
    groups, depth, open_at, unmatched = [], 0, -1, False
    for idx, ch in enumerate(item):
        if ch == "(":
            if depth == 0:
                open_at = idx
            depth += 1
        elif ch == ")":
            if depth == 0:
                unmatched = True
                continue
            depth -= 1
            if depth == 0:
                groups.append((open_at, idx + 1, item[open_at + 1: idx]))
    unclosed = depth > 0
    if unclosed:
        groups.append((open_at, len(item), item[open_at + 1:]))
    return groups, unclosed, unmatched


def _outside_parens(item: str, groups: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for s, e, _ in groups:
        spans.append((pos, s))
        pos = e
    spans.append((pos, len(item)))
    return spans


def _first_amount(text: str) -> re.Match | None:
    """한글 단어 중간 숫자 오탐을 피하려고, 앞이 공백·시작인 숫자만 분량으로 본다."""
    for m in _AMOUNT_RE.finditer(text):
        if m.start() == 0 or text[m.start() - 1].isspace() or text[m.start() - 1] in "(,":
            return m
    return None


def parse_item(item: str) -> dict:
    """원문 조각 하나 → 분할 결과(dict). 원문 조각은 앞뒤 공백만 떼어 낸 상태로 들어온다."""
    groups, unclosed, unmatched = _paren_scan(item)
    split_at, kind, fmt, amount, unit = None, "none", "none", None, None

    # 1) 괄호 밖의 숫자 분량 또는 정성 분량 (형식 A·Q)
    best = None
    for s, e in _outside_parens(item, groups):
        seg = item[s:e]
        m, q = _first_amount(seg), _QUAL_RE.search(seg)
        cands = [c for c in ((m, "measured"), (q, "qualitative")) if c[0] is not None]
        for match, k in cands:
            pos = s + match.start()
            if pos > 0 and (best is None or pos < best[0]):
                best = (pos, k, match)
        if best:
            break
    if best:
        split_at, kind, match = best
        if kind == "measured":
            fmt, amount, unit = "name_amount", parse_number(match.group("num")), match.group("unit")
        else:
            fmt = "qualitative"
    else:
        # 2) 숫자·정성 분량을 담은 첫 괄호 (형식 B·C)
        for s, _e, content in groups:
            m, q = _first_amount(content), _QUAL_RE.search(content)
            if s > 0 and (m or q):
                split_at, fmt = s, "paren_amount"
                if m:
                    kind, amount, unit = "measured", parse_number(m.group("num")), m.group("unit")
                else:
                    kind = "qualitative"
                break

    if split_at is None:
        name_raw, amount_text = item, ""
    else:
        name_raw, amount_text = item[:split_at].rstrip(), item[split_at:].lstrip()
    return {
        "name_raw": name_raw, "amount_text": amount_text,
        "paren_texts": [c for _s, _e, c in groups],
        "amount_kind": kind, "amount_format": fmt, "amount": amount, "unit": unit,
        "unclosed": unclosed, "unmatched": unmatched,
    }


def _is_title_line(line: str) -> bool:
    """숫자·쉼표·괄호·정성 분량이 없는 짧은 줄 = 메뉴명 또는 소제목."""
    return (len(line) <= 20 and not re.search(r"[\d,()]", line) and not _QUAL_RE.search(line))


def parse_ingredients(text: str | None) -> IngredientResult:
    if is_blank(text):
        return IngredientResult([], [], [Issue("ingredients_none")])
    source = nfc(text).replace("\r\n", "\n").replace("\r", "\n")
    ingredients: list[Ingredient] = []
    sections: list[Section] = []
    issues: list[Issue] = []
    section = ""

    for line_no, raw_line in enumerate(source.split("\n"), start=1):
        line = clean_text(raw_line)
        line = _SERVING_RE.sub("", line)          # "[1인분]" 표기는 섹션·재료가 아님
        line = _BULLET_RE.sub("", line).strip()
        if not line:
            continue
        # "양념장 : 간장 …" / "●방울토마토 소박이 :" (머리말에 숫자 없음)
        if ":" in line or "：" in line:
            head, rest = re.split(r"\s*[:：]\s*", line, maxsplit=1)
            if head and not re.search(r"\d", head) and len(head) <= 20:
                section = head.strip()
                sections.append(Section(line_no, raw_line, section, "colon"))
                line = rest.strip()
                if not line:
                    continue
        if _is_title_line(line):
            section = line
            sections.append(Section(line_no, raw_line, section, "title_line"))
            continue
        m = _INLINE_SECTION_RE.match(line)
        if m and re.search(r"[\d(]", line[m.end():]):
            section = m.group("sec")
            sections.append(Section(line_no, raw_line, section, "inline_word"))
            line = line[m.end():]

        parts, tight = _split_top_level(line)
        for comma_at in tight:
            issues.append(Issue("ingredient_no_space_after_comma",
                                {"line_no": line_no, "context": line[max(0, comma_at - 8): comma_at + 8]}))
        for _start, part in parts:
            item = part.strip()
            if item.endswith(".") and not re.search(r"\d\.$", item):
                issues.append(Issue("ingredient_trailing_period", {"line_no": line_no, "raw_item": item}))
                item = item[:-1].rstrip()
            if not item:
                continue  # 줄 끝 쉼표(다음 줄로 이어 씀)
            p = parse_item(item)
            ing = Ingredient(
                order_no=len(ingredients) + 1, line_no=line_no, section=section, raw_item=item,
                name_raw=p["name_raw"], amount_text=p["amount_text"], paren_texts=p["paren_texts"],
                amount_kind=p["amount_kind"], amount_format=p["amount_format"],
                amount=p["amount"], unit=p["unit"],
            )
            ingredients.append(ing)
            ref = {"order_no": ing.order_no, "line_no": line_no, "raw_item": item}
            if p["unclosed"]:
                issues.append(Issue("ingredient_unclosed_paren", ref))
            if p["unmatched"]:
                issues.append(Issue("ingredient_unmatched_close_paren", ref))
            if ing.amount_kind == "none":
                issues.append(Issue("ingredient_amount_missing", ref))
            elif ing.amount_kind == "qualitative":
                issues.append(Issue("ingredient_qualitative_amount", ref))
            elif ing.unit is None:
                issues.append(Issue("ingredient_unit_missing", ref))

    if not ingredients:
        issues.append(Issue("ingredients_unparsed"))
    formats = Counter(i.amount_format for i in ingredients if i.amount_format in ("name_amount", "paren_amount"))
    if len(formats) > 1:
        issues.append(Issue("ingredient_mixed_format", dict(formats)))
    return IngredientResult(ingredients, sections, issues)
