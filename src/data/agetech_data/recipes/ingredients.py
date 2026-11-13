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
     버터15g / 물60g(1/4컵)        이름에 붙여 쓴 분량 (앞이 글자, 단위 있음, 끝이나 괄호 앞)
     2가지색 파프리카 20g          숫자로 시작하는 이름 (맨 앞 숫자는 분량으로 보지 않음)
  섹션: "●양념장 : …", "•육수 : …", "재료 닭가슴살(60g)…"(콜론 없음), "• [주재료] 감자(100g)…"(대괄호),
        "주재료 > 달걀흰자 180g"(양옆 공백 '>'), 메뉴명·소제목 줄
  재료가 아닌 줄: "[1인분]" 머리표, "2인분 기준" 줄 (분량 기준 표기는 fields 의 ingredient_servings_stated)
  HTML 태그: 원문에 그대로 온 <br>·<br />·<strong> 은 줄바꿈, </strong> 은 지움 (2026-11 수집본 27건)
  줄 중간 구획: 쉼표·줄바꿈 없이 이어진 "… 9g [소스소개] 소스:양파 6g", "… 소금 0.5g - 양념장 : 고추 10g",
        "… 설탕 5g 된장소스:된장 1g" 은 그 자리에서 새 구획으로 나눈다 (ingredient_section_mid_line)
  쉼표 빠짐: 단위 있는 분량 바로 뒤에 다음 재료가 이어진 "떡볶이떡 40g 고추장 8g", "레드와인 200cc. 망고 50g" 은
        분량 뒤에서 나눈다 (ingredient_comma_missing). 크기 표기 "양파 1cm 정사각형 14g" 은 나누지 않는다
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
_SERVING_LINE_RE = re.compile(r"^\d+(?:\.\d+)?\s*인분(?:\s*기준)?$")      # "2인분 기준" 줄 전체
# "[주재료] 감자(100g), …" / 닫는 괄호가 빠진 "[소스소개 단촛물:물60g" (다음 낱말이 콜론 구획)
_BRACKET_SECTION_RE = re.compile(r"^\[(?:(?P<sec>[^\[\]]+)\]|(?P<open>[^\[\]:：,\s]+)\s+(?=[^\s:：,\[\]]+\s*[:：]))\s*")
_MID_BRACKET_RE = re.compile(r"\[(?:[^\[\]]+\]|[^\[\]:：,\s]+\s+(?=[^\s:：,\[\]]+\s*[:：]))")
_SEP_CHARS = " \t>-*.·"                    # 줄 중간 구획 앞에 붙은 구분 기호 ("20g >[소스소개]", "0.5g - 양념장 :")
_SERVINGS_SUFFIX_RE = re.compile(r"\(\d+\s*인분\)$")                       # "볶음고추장(5인분):" 의 분량 기준 표기
_SEC_NAME = r"[^\s\d,()\[\]:：*\-.·>][^\d,()\[\]:：]{0,19}?(?:\(\d+\s*인분\))?"
_SEC_HEAD_RE = re.compile(rf"^[-*·\s]*(?P<sec>{_SEC_NAME})\s*$")                     # ", - 멸치견과류쌈장 :"
_ITEM_SEC_HEAD_RE = re.compile(rf"^(?P<item>.*?\S)(?P<sep>\s+[-*]?\s*)(?P<sec>{_SEC_NAME})\s*$")  # "소금 0.5g - 양념장 :"
_NO_SPLIT_UNITS = {"cm"}                   # "양파 1cm 정사각형 14g": 크기 표기 뒤는 다음 재료가 아님
# 구획 머리말 뒤 구분자: 콜론, 또는 양옆이 공백인 '>' (2026-11 새 형식 "주재료 > 달걀흰자 180g", 10건)
_HEAD_SPLIT_RE = re.compile(r"\s*[:：]\s*|\s+>\s+")
_MARKUP_CLOSE_RE = re.compile(r"<\s*/\s*strong\s*>", re.I)
_MARKUP_BREAK_RE = re.compile(r"<\s*(?:br|strong)\s*/?\s*>", re.I)
_MARKUP_EOL_RE = re.compile(r"<\s*(?:br|strong)\s*/?\s*>[ \t]*(?=\n|$)", re.I)
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
    style: Literal["colon", "inline_word", "title_line", "bracket"]


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


def _first_amount(text: str, min_pos: int = 0) -> re.Match | None:
    """한글 단어 중간 숫자 오탐을 피하려고, 앞이 공백·시작인 숫자만 분량으로 본다.
    min_pos: 이 위치 앞의 숫자는 건너뜀 ("2가지색 파프리카 20g" 처럼 이름이 숫자로 시작할 때)."""
    for m in _AMOUNT_RE.finditer(text):
        if m.start() < min_pos:
            continue
        if m.start() == 0 or text[m.start() - 1].isspace() or text[m.start() - 1] in "(,":
            return m
    return None


# 이름에 붙어 쓴 분량 "버터15g", "물60g(1/4컵)": 앞이 글자이고 단위가 있으며 뒤가 끝이나 괄호일 때만
_GLUED_AMOUNT_RE = re.compile(rf"(?<=[가-힣A-Za-z])(?P<num>{_NUM})\s*(?P<unit>{_UNIT})(?=\s*(?:\(|$))")


def parse_item(item: str) -> dict:
    """원문 조각 하나 → 분할 결과(dict). 원문 조각은 앞뒤 공백만 떼어 낸 상태로 들어온다."""
    groups, unclosed, unmatched = _paren_scan(item)
    split_at, kind, fmt, amount, unit = None, "none", "none", None, None

    # 1) 괄호 밖의 숫자 분량 또는 정성 분량 (형식 A·Q)
    best = None
    for s, e in _outside_parens(item, groups):
        seg = item[s:e]
        m, q = _first_amount(seg, 1 if s == 0 else 0), _QUAL_RE.search(seg)
        cands = [c for c in ((m, "measured"), (q, "qualitative")) if c[0] is not None]
        for match, k in cands:
            pos = s + match.start()
            if pos > 0 and (best is None or pos < best[0]):
                best = (pos, k, match)
        if best:
            break
    head_start, head_end = _outside_parens(item, groups)[0]     # 첫 괄호 앞 조각
    glued = None if best else _GLUED_AMOUNT_RE.search(item[head_start:head_end].rstrip())
    if best:
        split_at, kind, match = best
        if kind == "measured":
            fmt, amount, unit = "name_amount", parse_number(match.group("num")), match.group("unit")
        else:
            fmt = "qualitative"
    elif glued:
        # 2) 이름에 붙여 쓴 분량 "버터15g", "물60g(1/4컵)" (괄호 밖 첫 조각 끝)
        split_at, kind, fmt = head_start + glued.start(), "measured", "name_amount"
        amount, unit = parse_number(glued.group("num")), glued.group("unit")
    else:
        # 3) 숫자·정성 분량을 담은 첫 괄호 (형식 B·C)
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


def _is_colon_head(head: str) -> bool:
    """줄(구획) 머리 콜론 앞이 구획 이름인가. 숫자 없는 20자 이하. '볶음고추장(5인분)'·'곁들이채소1' 도 구획."""
    core = _SERVINGS_SUFFIX_RE.sub("", head.strip()).strip()
    return bool(core) and len(core) <= 20 and (not re.search(r"\d", core) or bool(re.fullmatch(r"\D*[^\d\s]\d", core)))


def _inline_section(line: str) -> tuple[str, str] | None:
    """콜론 없는 머리말 "육수 다시마(5g)…" → (구획, 나머지). 뒤가 바로 분량이면("다시마육수 90g") 그 낱말은
    재료 이름이다. 머리말 뒤 분량 기준 표기("재료 1인분 봄동 10g")는 재료가 아니라 떼어 낸다."""
    m = _INLINE_SECTION_RE.match(line)
    if not m:
        return None
    rest = re.sub(r"^\d+\s*인분\s+", "", line[m.end():])
    return (m.group("sec"), rest) if re.search(r"[\d(]", rest) and not re.match(r"[\d(]", rest) else None


def _depth0_mask(line: str) -> list[bool]:
    """괄호 '(' ')' 밖 글자 위치 (괄호 글자 자체는 False)."""
    mask, depth = [], 0
    for ch in line:
        if ch == "(":
            depth += 1
            mask.append(False)
        elif ch == ")":
            depth = max(0, depth - 1)
            mask.append(False)
        else:
            mask.append(depth == 0)
    return mask


_AMOUNT_END_RE = re.compile(rf"(?:\d\s*(?:{_UNIT})?|\)|{_QUAL_RE.pattern})$")


def _mid_line_cuts(line: str) -> list[int]:
    """쉼표·줄바꿈 없이 줄 중간에서 새 구획이 시작하는 위치들 (줄 머리 구획은 줄 단위 처리가 본다).

    - "… 9g [소스소개] 소스:…" / "… 20g >[소스소개] …" : 대괄호 위치
    - "… 소금 0.5g - 양념장 : …" / "… 설탕 5g 된장소스:…" : 분량으로 끝난 재료 뒤, 콜론 앞 구획 이름 위치
    - "…, - 멸치견과류쌈장 : 다시마국물 10g" : 쉼표 바로 뒤 구획 이름 (콜론 뒤가 숫자면 '이름: 분량' 이라 제외)
    """
    mask = _depth0_mask(line)
    cuts: set[int] = set()
    bracket_ends: list[int] = []
    for m in _MID_BRACKET_RE.finditer(line):
        if not mask[m.start()] or _SERVING_RE.match(line[m.start():]):
            continue
        bracket_ends.append(m.end())
        if line[:m.start()].strip(_SEP_CHARS):
            cuts.add(m.start())
    for c, ch in enumerate(line):
        is_gt = ch == ">" and line[c - 1:c].isspace() and line[c + 1:c + 2].isspace()
        if not (ch in ":：" or is_gt) or not mask[c]:
            continue
        start = next((k + 1 for k in range(c - 1, -1, -1) if mask[k] and line[k] in ",，"), 0)
        start = max([start] + [e for e in bracket_ends if e <= c])
        head, rest = line[start:c], line[c + 1:].lstrip()
        m = _ITEM_SEC_HEAD_RE.match(head)
        if m and _AMOUNT_END_RE.search(m.group("item")):
            cuts.add(start + m.end("item"))
        elif start and start not in bracket_ends and _SEC_HEAD_RE.match(head) and rest and not rest[0].isdigit():
            cuts.add(start)
    return sorted(cuts)


def _split_glued(item: str) -> list[str]:
    """쉼표가 빠져 붙은 재료를 나눈다: '떡볶이떡 40g 고추장 8g' → ['떡볶이떡 40g', '고추장 8g'].

    앞 재료가 단위 있는 숫자 분량이고(크기 'cm' 제외), 그 분량(과 바로 뒤 괄호) 다음에 공백·마침표를 두고
    숫자 없는 이름 + 단위 있는 숫자 분량이 올 때만 나눈다. 원문 조각은 고치지 않고 자르기만 한다.
    """
    p = parse_item(item)
    if p["amount_kind"] != "measured" or not p["unit"] or p["unit"] in _NO_SPLIT_UNITS:
        return [item]
    amount_text = p["amount_text"]
    if p["amount_format"] == "name_amount":
        m = _AMOUNT_RE.match(amount_text)
        end = m.end() if m else len(amount_text)
        if amount_text[end:end + 1] == "(":
            groups, _, _ = _paren_scan(amount_text[end:])
            end += groups[0][1] if groups else len(amount_text) - end
    else:
        groups, _, _ = _paren_scan(amount_text)
        end = groups[0][1] if groups else len(amount_text)
    m = re.match(r"(?:\.\s*|\s+|(?=[가-힣]))(?P<next>[가-힣].*)$", amount_text[end:])
    if not m:
        return [item]
    nxt = m.group("next")
    q = parse_item(nxt)
    if q["amount_kind"] != "measured" or not q["unit"] or not q["name_raw"] or re.search(r"\d", q["name_raw"]):
        return [item]
    head = item[:len(item) - len(amount_text) + end]
    return [head, *_split_glued(nxt)]


def parse_ingredients(text: str | None) -> IngredientResult:
    if is_blank(text):
        return IngredientResult([], [], [Issue("ingredients_none")])
    source = nfc(text).replace("\r\n", "\n").replace("\r", "\n")
    # HTML 줄바꿈 태그: 줄 끝 태그는 지우기만 하고(줄 번호 그대로), 줄 중간 태그는 줄바꿈으로 본다
    source = _MARKUP_EOL_RE.sub("", _MARKUP_CLOSE_RE.sub("", source))
    source = _MARKUP_BREAK_RE.sub("\n", source)
    ingredients: list[Ingredient] = []
    sections: list[Section] = []
    issues: list[Issue] = []
    section = ""

    for line_no, raw_line in enumerate(source.split("\n"), start=1):
        line = clean_text(raw_line)
        line = _SERVING_RE.sub("", line)          # "[1인분]" 표기는 섹션·재료가 아님
        line = _BULLET_RE.sub("", line).strip()
        if not line or _SERVING_LINE_RE.match(line):   # "2인분 기준" 줄은 재료가 아님
            continue
        cuts = _mid_line_cuts(line)
        for cut in cuts:
            issues.append(Issue("ingredient_section_mid_line",
                                {"line_no": line_no, "context": line[max(0, cut - 12): cut + 16]}))
        bounds = [0, *cuts, len(line)]
        for seg_no in range(len(bounds) - 1):
            seg = line[bounds[seg_no]:bounds[seg_no + 1]]
            if seg_no + 1 < len(bounds) - 1:           # 다음 구획 앞 구분 기호(" - ", " >", 쉼표)는 재료가 아님
                seg = seg.rstrip(_SEP_CHARS + ",，")
            seg = seg.lstrip(_SEP_CHARS).strip() if seg_no else seg.strip()
            section = _parse_segment(seg, seg_no, line_no, raw_line, section, ingredients, sections, issues)

    if not ingredients:
        issues.append(Issue("ingredients_unparsed"))
    formats = Counter(i.amount_format for i in ingredients if i.amount_format in ("name_amount", "paren_amount"))
    if len(formats) > 1:
        issues.append(Issue("ingredient_mixed_format", dict(formats)))
    return IngredientResult(ingredients, sections, issues)


def _parse_segment(line: str, seg_no: int, line_no: int, raw_line: str, section: str,
                   ingredients: list[Ingredient], sections: list[Section], issues: list[Issue]) -> str:
    """줄(또는 줄 중간 구획 하나)을 구획 머리말·재료로 나눈다. 바뀐 현재 구획 이름을 돌려준다."""
    if not line:
        return section
    m = _BRACKET_SECTION_RE.match(line)            # 대괄호 섹션 이름이 첫 재료 이름에 붙지 않게
    if m:
        section = (m.group("sec") or m.group("open")).strip()
        sections.append(Section(line_no, raw_line, section, "bracket"))
        line = line[m.end():].strip()
        if not line:
            return section
    # "양념장 : 간장 …" / "●방울토마토 소박이 :" / "- 소스 : …" / "주재료 > 달걀흰자 …" (머리말에 숫자 없음)
    if _HEAD_SPLIT_RE.search(line):
        head, rest = _HEAD_SPLIT_RE.split(line, maxsplit=1)
        if _is_colon_head(head.lstrip("-*· ")):
            section = head.strip().lstrip("-*· ").strip()
            sections.append(Section(line_no, raw_line, section, "colon"))
            line = rest.strip()
            if not line:
                return section
    if seg_no == 0 and _is_title_line(line):        # 줄 중간 구획 뒤는 재료 (제목 줄 아님)
        sections.append(Section(line_no, raw_line, line, "title_line"))
        return line
    inline = _inline_section(line)
    if inline:
        section, line = inline
        sections.append(Section(line_no, raw_line, section, "inline_word"))

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
        pieces = _split_glued(item)
        if len(pieces) > 1:
            issues.append(Issue("ingredient_comma_missing", {"line_no": line_no, "raw_item": item}))
        for piece_no, piece in enumerate(pieces):
            inline = _inline_section(piece) if piece_no else None   # "방울토마토(20g) 소스 통계피(20g)"
            if inline:
                section, piece = inline
                sections.append(Section(line_no, raw_line, section, "inline_word"))
            _add_item(piece, line_no, section, ingredients, issues)
    return section


def _add_item(item: str, line_no: int, section: str, ingredients: list[Ingredient], issues: list[Issue]) -> None:
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
