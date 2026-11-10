"""복지·레시피 정제 결과 → RAG 검색 청크 (표준 라이브러리만).

청크 하나 = docs/data/sql/rag_chunk_draft.sql 의 rag_chunk 한 행(embedding 칸 제외).
규칙은 docs/data/rag_embedding_decision.md 4절:
- 복지 사업 1건 = 1청크. 너무 길면 개요·지원 내용·신청 항목 경계로 나눈다.
- 레시피 1건 = 1청크. 너무 길면 만드는 법을 따로 나눈다. hold 레시피는 만들지 않는다.
- 모든 청크 앞에 '[복지] 사업명 (지역)' / '[레시피] 이름' 머리말을 붙여, 나눈 조각만 봐도 무엇인지 알게 한다.
- 대상·기준 문장은 원문 그대로 둔다(수급 자격을 판정하는 문장을 만들지 않는다).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field

from agetech_data.welfare.revision import content_sha256 as welfare_content_sha256

MAX_CHARS = 1000            # 이보다 긴 문서는 항목 경계로 나눈다
MAX_CONTACTS = 5            # 본문에 넣는 문의처 수 (나머지는 원본 표에서)

_SENT_END = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class Chunk:
    chunk_id: str
    source_type: str                 # welfare_central / welfare_local / recipe
    source_id: str
    section: str                     # all / overview / benefits / apply / steps
    chunk_no: int
    title: str
    content: str
    content_sha256: str
    region_scope: str                # national / province / district / none
    ctpv: str | None
    sgg: str | None
    source_url: str | None
    source_checked_at: str | None
    source_modified: str | None
    period_end: str | None
    quality_status: str              # ok / flagged
    data_version: str
    # 원본 표 판본과 맞출 해시 — 복지: 정제 레코드 내용 해시(= DB welfare_revisions.content_sha256),
    # 레시피: 원본 행 해시(= recipe_revisions.raw_sha256). DB 적재 때 게시 판본 fingerprint 로 바꿔 넣는다
    source_record_sha256: str | None = None
    quality_flags: list[str] = field(default_factory=list)
    allergens: list[str] = field(default_factory=list)
    status: str = "active"

    def to_dict(self) -> dict:
        return asdict(self)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _tidy(s: str | None) -> str:
    """앞뒤 공백·연속 빈 줄만 정리 (내용은 바꾸지 않음)."""
    if not s:
        return ""
    lines = [ln.rstrip() for ln in s.strip().splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln.strip() or (out and out[-1].strip()):
            out.append(ln)
    return "\n".join(out).strip()


def _split_long(body: str, limit: int) -> list[str]:
    """limit 자 이하 조각으로. 줄·문장 경계를 먼저 지키고, 그래도 길면 글자 수로 자른다."""
    if len(body) <= limit:
        return [body]
    pieces = [p.strip() for p in _SENT_END.split(body) if p and p.strip()]
    out, buf = [], ""
    for p in pieces:
        while len(p) > limit:
            if buf:
                out.append(buf)
                buf = ""
            out.append(p[:limit])
            p = p[limit:]
        if buf and len(buf) + 1 + len(p) > limit:
            out.append(buf)
            buf = ""
        buf = f"{buf}\n{p}" if buf else p
    if buf:
        out.append(buf)
    return out


def _assemble(header: str, sections: list[tuple[str, list[str]]], max_chars: int) -> list[tuple[str, str]]:
    """[(section, content)]. 전체가 짧으면 ('all', 하나), 길면 항목별 → 그래도 길면 문장 경계로."""
    blocks = [(name, "\n".join(x for x in lines if x)) for name, lines in sections]
    blocks = [(name, body) for name, body in blocks if body]
    whole = header + "\n" + "\n".join(body for _, body in blocks)
    if len(whole) <= max_chars:
        return [("all", whole)]
    out = []
    limit = max(200, max_chars - len(header) - 1)
    for name, body in blocks:
        for piece in _split_long(body, limit):
            out.append((name, header + "\n" + piece))
    return out


# ── 복지 ────────────────────────────────────────────────────────────────

def region_label(scope: str, ctpv: str | None, sgg: str | None) -> str:
    if scope == "national":
        return "전국"
    if scope == "province":
        return f"{ctpv} 전체"
    return f"{ctpv} {sgg}"


def _entries(items: list[dict], limit: int | None = None, strip_suffix: bool = False) -> list[str]:
    out = []
    for e in items[:limit] if limit else items:
        name, value = (e.get("name") or "").strip(), (e.get("value") or "").strip()
        if strip_suffix:
            name = name.replace("연락처목록", "").replace("목록", "")
        if name and value:
            out.append(f"{name}: {value}")
        elif name or value:
            out.append(name or value)
    return out


def welfare_chunks(rec: dict, data_version: str, max_chars: int = MAX_CHARS) -> list[Chunk]:
    """정제 레코드(dict, welfare_contract.md 2절) → 청크."""
    scope = rec["scope"]
    ctpv = rec.get("ctpv") if scope != "national" else None
    sgg = rec.get("sgg") if scope == "district" else None
    name = _tidy(rec.get("name")) or rec["serv_id"]
    header = f"[복지] {name} ({region_label(scope, ctpv, sgg)})"

    def line(label: str, v: str | None) -> str:
        v = _tidy(v)
        return f"{label}: {v}" if v else ""

    apply_methods = ", ".join(rec.get("apply_methods") or [])
    guides = _entries(rec.get("apply_guides") or [], strip_suffix=True)
    contacts = _entries(rec.get("contacts") or [], MAX_CONTACTS)
    if not contacts and rec.get("main_contact"):
        contacts = [rec["main_contact"]]
    office = rec.get("department") or rec.get("ministry")
    provision = ", ".join(rec.get("provision_types") or [])

    sections = [
        ("overview", [line("요약", rec.get("summary")),
                      line("지원 대상", rec.get("target_detail")),
                      line("선정 기준", rec.get("selection_criteria"))]),
        ("benefits", [line("지원 내용", rec.get("benefits")),
                      line("지원 주기", rec.get("support_cycle")),
                      line("제공 방식", provision)]),
        ("apply", [line("신청 방법", apply_methods),
                   _tidy(rec.get("apply_detail")),
                   ("신청 안내:\n" + "\n".join(guides)) if guides else "",
                   ("문의처: " + " / ".join(contacts)) if contacts else "",
                   line("담당", office)]),
    ]
    source_type = f"welfare_{rec['source']}"
    flags = list(rec.get("quality_flags") or []) + [f"unverified:{f}" for f in rec.get("unverified_fields") or []]
    out = []
    for no, (section, content) in enumerate(_assemble(header, sections, max_chars), start=1):
        out.append(Chunk(
            chunk_id=f"{source_type}:{rec['serv_id']}:{section}:{no}",
            source_type=source_type, source_id=rec["serv_id"], section=section, chunk_no=no,
            title=name, content=content, content_sha256=sha256_text(content),
            region_scope=scope, ctpv=ctpv, sgg=sgg,
            source_url=rec.get("detail_url"),
            source_checked_at=rec.get("detail_fetched_at") or rec.get("source_fetched_at"),
            source_modified=rec.get("last_modified"), period_end=rec.get("period_end"),
            quality_status="ok", data_version=data_version, source_record_sha256=welfare_content_sha256(rec),
            quality_flags=flags,
        ))
    return out


# ── 레시피 ──────────────────────────────────────────────────────────────

def _num(v: float | None) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else "?"


def recipe_chunks(rec: dict, data_version: str, max_chars: int = MAX_CHARS) -> list[Chunk]:
    """레시피 계약 레코드(recipe_contract.md) → 청크. hold 는 []."""
    q = rec.get("quality") or {}
    if q.get("status") == "hold":
        return []
    name = _tidy(rec.get("name")) or rec["recipe_id"]
    header = f"[레시피] {name}"
    kind = " · ".join(x for x in [
        f"분류: {rec['category']}" if rec.get("category") else "",
        f"조리법: {rec['cooking_method']}" if rec.get("cooking_method") else "",
        f"해시태그: {rec['hashtag']}" if rec.get("hashtag") else "",
    ] if x)
    ingredients = " / ".join(ln.strip() for ln in (rec.get("ingredients_text") or "").splitlines() if ln.strip())
    steps = [f"{s['no']}. {_tidy(s.get('text'))}" for s in rec.get("steps") or [] if _tidy(s.get("text"))]
    n = rec.get("nutrition") or {}
    nutrition = ""
    if n and not n.get("suspect") and n.get("energy_kcal") is not None:
        nutrition = (f"영양(원문 값, 기준량 미확인): 열량 {_num(n.get('energy_kcal'))}kcal · "
                     f"탄수화물 {_num(n.get('carbohydrate_g'))}g · 단백질 {_num(n.get('protein_g'))}g · "
                     f"지방 {_num(n.get('fat_g'))}g · 나트륨 {_num(n.get('sodium_mg'))}mg")
    sections = [
        ("overview", [kind,
                      f"재료: {ingredients}" if ingredients else "",
                      f"저염 팁: {_tidy(rec.get('sodium_tip'))}" if _tidy(rec.get("sodium_tip")) else "",
                      nutrition]),
        ("steps", [("만드는 법:\n" + "\n".join(steps)) if steps else ""]),
    ]
    flags = [i["code"] for i in q.get("issues") or [] if i.get("code")]
    if n.get("suspect"):
        flags.append("nutrition_suspect")
    if rec.get("missing_step_nos"):
        flags.append("steps_missing")
    allergens = sorted({d["allergen"] for d in (rec.get("allergens") or {}).get("detected") or [] if d.get("allergen")})
    src = rec.get("source") or {}
    out = []
    for no, (section, content) in enumerate(_assemble(header, sections, max_chars), start=1):
        out.append(Chunk(
            chunk_id=f"recipe:{rec['recipe_id']}:{section}:{no}",
            source_type="recipe", source_id=str(rec["recipe_id"]), section=section, chunk_no=no,
            title=name, content=content, content_sha256=sha256_text(content),
            region_scope="none", ctpv=None, sgg=None, source_url=None,
            source_checked_at=src.get("fetched_at"), source_modified=None, period_end=None,
            quality_status="flagged" if q.get("status") == "flagged" else "ok",
            data_version=data_version, source_record_sha256=src.get("raw_sha256"),
            quality_flags=sorted(set(flags)), allergens=allergens,
        ))
    return out


# ── 묶음 ────────────────────────────────────────────────────────────────

def _version(input_meta: dict | None, label: str) -> str:
    sha = (input_meta or {}).get("sha256") or ""
    return f"{label}:{sha[:12]}" if sha else f"{label}:unknown"


def build_chunks(welfare_payload: dict | None, recipe_payload: dict | None,
                 max_chars: int = MAX_CHARS) -> list[Chunk]:
    """정제 파일 내용(welfare_elderly.json, recipes_api_all.json) → 전체 청크. 순서는 원천·ID 순으로 고정."""
    chunks: list[Chunk] = []
    if welfare_payload:
        inputs = welfare_payload.get("input") or {}
        versions = {src: _version(inputs.get(src), f"welfare_{src}") for src in ("central", "local")}
        for rec in sorted(welfare_payload["records"], key=lambda r: (r["source"], r["serv_id"])):
            chunks += welfare_chunks(rec, versions[rec["source"]], max_chars)
    if recipe_payload:
        version = _version(recipe_payload.get("input"), "recipes")
        for rec in sorted(recipe_payload["records"], key=lambda r: (len(str(r["recipe_id"])), str(r["recipe_id"]))):
            chunks += recipe_chunks(rec, version, max_chars)
    ids = [c.chunk_id for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("chunk_id 중복 — 원천 ID가 겹침")
    return chunks
