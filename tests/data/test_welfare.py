import json
from datetime import date

import pytest

from agetech_data import paths
from agetech_data.welfare import build
from agetech_data.welfare.normalize import (clean_text, is_placeholder_form, normalize_item, normalize_payload, parse_ymd,
                                            split_list)
from agetech_data.welfare.query import services_for
from agetech_data.welfare.regions import MERGED, match_sgg, normalize_ctpv, normalize_sgg

AS_OF = date(2026, 11, 1)

# 실제 원천 필드 이름·값 형태를 따른 항목 (중앙: 상세 있음 / 지자체: 상세 없음·있음)
CENTRAL = {
    "servId": "WLF00003191", "detail_status": "fresh", "detail_fetched_at": "2026-11-02T00:00:00+00:00",
    "list": {"servId": "WLF00003191", "servNm": "노인맞춤돌봄서비스", "servDgst": "취약노인에게 돌봄서비스를 제공합니다.",
             "lifeArray": "노년", "trgterIndvdlArray": "저소득", "intrsThemaArray": "생활지원,안전·위기,보호·돌봄",
             "jurMnofNm": "보건복지부", "jurOrgNm": "노인정책과", "rprsCtadr": "129", "onapPsbltYn": "Y",
             "sprtCycNm": "수시", "srvPvsnNm": "현물지급,프로그램/서비스(서비스)", "svcfrstRegTs": "20210903",
             "inqNum": "288017",
             "servDtlLink": "https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId=WLF00003191"},
    "detail": {"servId": "WLF00003191", "tgtrDtlCn": "65세 이상 &lt;br&gt;①국민기초생활 수급자", "slctCritCn": "돌봄필요도에 따라",
               "alwServCn": "방문형 서비스&amp;연계 서비스", "crtrYr": "2026"},
    "detail_xml": ("<wantedDtl><resultCode>0</resultCode><servId>WLF00003191</servId>"
                   "<inqplCtadrList><servSeDetailNm>보건복지상담센터</servSeDetailNm><servSeDetailLink>129</servSeDetailLink>"
                   "</inqplCtadrList><baslawList><servSeDetailNm>노인복지법</servSeDetailNm></baslawList></wantedDtl>"),
}


def _local(sid, ctpv, sgg, name="사업", status="pending", detail=None, mod="20261028"):
    item = {"servId": sid, "detail_status": status,
            "list": {"servId": sid, "servNm": name, "servDgst": f"{name} 요약", "ctpvNm": ctpv, "sggNm": sgg,
                     "lifeNmArray": "노년, 중장년", "trgterIndvdlNmArray": "", "aplyMtdNm": "방문, 전화",
                     "bizChrDeptNm": f"{ctpv} {sgg} 복지과", "lastModYmd": mod, "sprtCycNm": "월", "srvPvsnNm": "현금지급",
                     "inqNum": "10", "servDtlLink": f"https://www.bokjiro.go.kr/x?wlfareInfoId={sid}"}}
    if detail:
        item.update(detail=detail, detail_xml="<wantedDtl><resultCode>0</resultCode></wantedDtl>")
    return item


def _records():
    loc = [
        _local("WLF00000001", "경상북도", "경산시", "경산 효도수당"),
        _local("WLF00000002", "경상북도", "", "경북 전체 사업"),
        _local("WLF00000003", "경상북도", "구미시", "구미 사업"),
        _local("WLF00000004", "전남광주통합특별시", "광산구", "광산구 장수수당"),
        _local("WLF00000005", "전남광주통합특별시", "순천시", "순천 사업"),
        _local("WLF00000006", "대구광역시", "중구", "대구 중구 사업"),
        _local("WLF00000007", "서울특별시", "중구", "서울 중구 사업"),
        _local("WLF00000008", "경상북도", "경산시", "끝난 사업", status="fresh",
               detail={"servId": "WLF00000008", "sprtTrgtCn": "65세 이상", "enfcEndYmd": "20251231"}),
    ]
    central = normalize_payload({"meta": {"fetched_at": "2026-11-01T00:00:00+00:00"}, "items": [CENTRAL]}, "central")
    local = normalize_payload({"meta": {"fetched_at": "2026-11-01T00:00:00+00:00"}, "items": loc}, "local")
    return central + local


# --- 지역 정규화 ----------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("서울특별시", "서울특별시"), ("서울", "서울특별시"), ("강원도", "강원특별자치도"), ("전라북도", "전북특별자치도"),
    ("광주광역시", MERGED), ("전라남도", MERGED), ("전남광주통합특별시", MERGED), (" 경 북 ", "경상북도"),
    ("제주도", "제주특별자치도"), ("없는도", None), ("", None), (None, None),
])
def test_normalize_ctpv(raw, expected):
    assert normalize_ctpv(raw) == expected


def test_match_sgg():
    known = {"경산시", "구미시", "중구", "수성구"}
    assert match_sgg("경산", known) == "경산시" and match_sgg("경산 시", known) == "경산시"
    assert match_sgg("수성", known) == "수성구" and match_sgg("중구", known) == "중구"
    assert match_sgg("포항", known) is None and match_sgg("", known) is None


# --- 정제 -----------------------------------------------------------------
def test_text_list_date_helpers():
    assert clean_text("A &amp;lt;br&amp;gt; B<br/>C <b>굵게</b>") == "A\nB\nC 굵게"
    assert split_list("노년, 중장년") == ["노년", "중장년"] and split_list("청년,중장년,노년") == ["청년", "중장년", "노년"]
    assert parse_ymd("20261028") == ("2026-10-28", True)
    assert parse_ymd("") == (None, True) and parse_ymd("2026-13-01") == (None, False)


def test_central_record_with_detail():
    r = normalize_item(CENTRAL, "central", "2026-11-01T00:00:00+00:00", AS_OF)
    assert (r.scope, r.ctpv, r.sgg) == ("national", None, None)
    assert r.target_detail == "65세 이상\n①국민기초생활 수급자" and r.benefits == "방문형 서비스&연계 서비스"
    assert r.themes == ["생활지원", "안전·위기", "보호·돌봄"] and r.online_apply is True
    assert r.contacts == [{"name": "보건복지상담센터", "value": "129",
                           "raw": {"servSeDetailNm": "보건복지상담센터", "servSeDetailLink": "129"}}]
    assert r.laws == [{"name": "노인복지법", "value": None, "raw": {"servSeDetailNm": "노인복지법"}}]
    assert r.first_registered == "2021-09-03" and r.unverified_fields == []
    assert r.quality_flags == [] and r.detail_status == "fresh"


def test_local_pending_record_marks_unverified():
    r = normalize_item(_local("WLF00000001", "경상북도", "경산시"), "local", None, AS_OF)
    assert (r.scope, r.ctpv, r.sgg) == ("district", "경상북도", "경산시")
    assert r.apply_methods == ["방문", "전화"] and r.last_modified == "2026-10-28"
    assert set(r.unverified_fields) == {"target_detail", "selection_criteria", "benefits", "apply_detail", "contacts"}
    assert "detail_pending" in r.quality_flags
    prov = normalize_item(_local("WLF00000002", "강원도", ""), "local", None, AS_OF)
    assert (prov.scope, prov.ctpv, prov.ctpv_raw) == ("province", "강원특별자치도", "강원도")


def test_local_detail_entries_use_common_keys_and_link_status():
    """지자체 상세는 하위 태그가 wlfareInfo… — 중앙과 같은 name/value 로 맞추고, 주소가 아닌 홈페이지는 표시한다."""
    xml = ("<wantedDtl><resultCode>0</resultCode>"
           "<inqplCtadrList><wlfareInfoDtlCd>010</wlfareInfoDtlCd><wlfareInfoReldNm>경산시 노인장애인과</wlfareInfoReldNm>"
           "<wlfareInfoReldCn>053-810-5000</wlfareInfoReldCn></inqplCtadrList>"
           "<inqplHmpgReldList><wlfareInfoReldNm>경산시청</wlfareInfoReldNm>"
           "<wlfareInfoReldCn>https://www.gbgs.go.kr</wlfareInfoReldCn></inqplHmpgReldList>"
           "<inqplHmpgReldList><wlfareInfoReldNm>치매안심센터</wlfareInfoReldNm>"
           "<wlfareInfoReldCn>gbgs.nid.or.kr/</wlfareInfoReldCn></inqplHmpgReldList>"
           "<inqplHmpgReldList><wlfareInfoReldNm>목포시청 노인장애인과</wlfareInfoReldNm>"
           "<wlfareInfoReldCn>목포시청</wlfareInfoReldCn></inqplHmpgReldList>"
           "<inqplHmpgReldList><wlfareInfoDtlCd>020</wlfareInfoDtlCd></inqplHmpgReldList>"  # 코드만 있는 빈 항목
           "<basfrmList><wlfareInfoReldNm>신청서.hwp</wlfareInfoReldNm>"
           "<wlfareInfoReldCn>https://www.bokjiro.go.kr/f?id=1&amp;sn=1</wlfareInfoReldCn></basfrmList>"
           "</wantedDtl>")
    item = _local("WLF00000010", "경상북도", "경산시", status="fresh",
                  detail={"servId": "WLF00000010", "sprtTrgtCn": "65세 이상", "slctCritCn": "소득", "alwServCn": "월 3만원",
                          "aplyMtdCn": "주민센터 방문"})
    item["detail_xml"] = xml
    r = normalize_item(item, "local", None, AS_OF)
    assert [(c["name"], c["value"]) for c in r.contacts] == [("경산시 노인장애인과", "053-810-5000")]
    assert r.contacts[0]["raw"]["wlfareInfoReldCn"] == "053-810-5000"
    assert [(h["url"], h["link_status"]) for h in r.homepages] == [
        ("https://www.gbgs.go.kr", "ok"), ("https://gbgs.nid.or.kr/", "scheme_added"), (None, "not_url")]
    assert r.homepages[2]["value"] == "목포시청"
    assert (r.forms[0]["url"], r.forms[0]["link_status"]) == ("https://www.bokjiro.go.kr/f?id=1&sn=1", "ok")
    assert "homepage_not_url" in r.quality_flags and r.unverified_fields == []
    assert "placeholder_form" not in r.quality_flags


@pytest.mark.parametrize("name,placeholder", [("첨부파일없음.hwp", True), ("없음.hwp", True), ("첨부 파일 없음.pdf", True),
                                              ("신청서.hwp", False), ("없음안내문.hwp", False)])
def test_placeholder_forms_are_dropped(name, placeholder):
    """'첨부파일없음.hwp'는 내려받을 서식이 아니다 — 서식 목록에서 빼고 사업에 표시한다(원문은 data/raw 그대로)."""
    xml = ("<wantedDtl><resultCode>0</resultCode>"
           f"<basfrmList><wlfareInfoReldNm>{name}</wlfareInfoReldNm>"
           "<wlfareInfoReldCn>https://www.bokjiro.go.kr/f?id=9&amp;sn=1</wlfareInfoReldCn></basfrmList>"
           "<basfrmList><wlfareInfoReldNm>신청서2.hwp</wlfareInfoReldNm>"
           "<wlfareInfoReldCn>https://www.bokjiro.go.kr/f?id=9&amp;sn=2</wlfareInfoReldCn></basfrmList>"
           "</wantedDtl>")
    item = _local("WLF00000011", "경상북도", "경산시", status="fresh", detail={"servId": "WLF00000011"})
    item["detail_xml"] = xml
    r = normalize_item(item, "local", None, AS_OF)
    names = [f["name"] for f in r.forms]
    assert (name not in names) == placeholder and "신청서2.hwp" in names
    assert ("placeholder_form" in r.quality_flags) == placeholder


def test_period_ended_and_unknown_ctpv_flags():
    ended = normalize_item(_local("WLF00000008", "경상북도", "경산시", status="fresh",
                                  detail={"servId": "WLF00000008", "enfcEndYmd": "20251231"}), "local", None, AS_OF)
    assert "period_ended" in ended.quality_flags and ended.period_end == "2025-12-31"
    odd = normalize_item(_local("WLF00000009", "가상도", "어딘가"), "local", None, AS_OF)
    assert odd.ctpv is None and "unknown_ctpv" in odd.quality_flags


@pytest.mark.parametrize("sgg_raw", ["-", " - ", "－", "", None])
def test_placeholder_sgg_is_province_wide(sgg_raw):
    # 원천 시군구 칸이 '-'인 사업(실데이터 WLF00004534 대구·WLF00004142 경기)은 시도 전체 사업이다
    r = normalize_item(_local("WLF00000010", "대구광역시", sgg_raw), "local", None, AS_OF)
    assert (r.scope, r.ctpv, r.sgg) == ("province", "대구광역시", None)
    assert normalize_sgg(sgg_raw) is None and normalize_sgg("남구") == "남구"


# --- 지역별 조회 ----------------------------------------------------------
def _names(matches):
    return [(m["match"], m["record"].name) for m in matches]


def test_services_for_order_and_scope():
    q, m = services_for(_records(), "경상북도", "경산")
    assert (q.ctpv, q.sgg) == ("경상북도", "경산시")
    assert _names(m) == [("district", "경산 효도수당"), ("province", "경북 전체 사업"), ("national", "노인맞춤돌봄서비스")]
    # 구미 사업·끝난 사업은 빠짐
    _, m2 = services_for(_records(), "경상북도", "경산", include_ended=True)
    assert ("district", "끝난 사업") in _names(m2)


def test_services_for_merged_region_and_same_name_district():
    q, m = services_for(_records(), "광주광역시", "광산")
    assert q.ctpv == MERGED and q.sgg == "광산구" and "통합" in q.notes[0]
    assert ("district", "광산구 장수수당") in _names(m) and ("district", "순천 사업") not in _names(m)
    _, m = services_for(_records(), "대구광역시", "중구")
    assert ("district", "대구 중구 사업") in _names(m) and ("district", "서울 중구 사업") not in _names(m)


def test_services_for_unknown_inputs():
    q, m = services_for(_records(), "없는도", "어딘가")
    assert q.ctpv is None and [x["match"] for x in m] == ["national"] and q.notes
    q, m = services_for(_records(), "경상북도", "포항시")
    assert q.sgg is None and "포항시" in q.notes[0]
    assert {x["match"] for x in m} == {"province", "national"}


# --- CLI ------------------------------------------------------------------
def test_build_main_end_to_end(tmp_path):
    meta = {"fetched_at": "2026-11-01T00:00:00+00:00", "item_count": 1, "details": {"counts": {"fresh": 1}}}
    c = tmp_path / "c.json"
    c.write_text(json.dumps({"meta": meta, "items": [CENTRAL]}, ensure_ascii=False), encoding="utf-8")
    loc = tmp_path / "l.json"
    loc.write_text(json.dumps({"meta": meta, "items": [_local("WLF00000001", "경상북도", "경산시")]},
                              ensure_ascii=False), encoding="utf-8")
    args = ["--central", str(c), "--local", str(loc), "--output", str(tmp_path / "o.json"), "--report", str(tmp_path / "r.md")]
    assert build.main(args) == 0
    first = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert build.main(args) == 0 and (tmp_path / "r.md").read_text(encoding="utf-8") == first
    out = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))
    assert out["summary"]["by_scope"] == {"national": 1, "district": 1}
    assert build.main(["--central", str(tmp_path / "none.json"), "--no-report"]) == 1


@pytest.mark.skipif(not (paths.WELFARE_CENTRAL_RAW.is_file() and paths.WELFARE_LOCAL_RAW.is_file()),
                    reason="복지 원문 없음 (refresh 실행 필요)")
def test_real_welfare_regression():
    central = json.loads(paths.WELFARE_CENTRAL_RAW.read_text(encoding="utf-8"))
    local = json.loads(paths.WELFARE_LOCAL_RAW.read_text(encoding="utf-8"))
    recs = normalize_payload(central, "central") + normalize_payload(local, "local")
    assert len(recs) == len(central["items"]) + len(local["items"])
    assert not [r for r in recs if "unknown_ctpv" in r.quality_flags]  # 원천 시도명 모두 인식
    assert all(r.name and r.detail_url for r in recs)
    assert len({r.serv_id for r in recs}) == len(recs)
    # 상세 목록형 항목은 중앙·지자체 모두 공통 키로 읽힌다
    entries = [e for r in recs for e in r.contacts + r.homepages + r.apply_guides + r.laws + r.forms]
    assert all(e["name"] or e["value"] for e in entries)
    assert {e["link_status"] for r in recs for e in r.homepages + r.forms} <= {"ok", "scheme_added", "not_url"}
    assert not [f for r in recs for f in r.forms if is_placeholder_form(f)]   # 자리 표시 서식은 남지 않는다
    assert sum("placeholder_form" in r.quality_flags for r in recs) >= 80     # 11/06 수집본 88개 사업
    fresh =[r for r in recs if r.detail_status == "fresh"]
    assert sum(bool(r.target_detail) for r in fresh) >= 0.95 * len(fresh)
    q, m = services_for(recs, "광주광역시", "광산구")
    assert q.ctpv == MERGED and any(x["match"] == "district" for x in m)
