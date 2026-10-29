"""Fetch central welfare list and details using the supplied v2.2 API guide."""

import argparse
from datetime import datetime, timezone
from html import unescape
import re
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
import xml.etree.ElementTree as ET

from api_config import load_api_key
from fetch_recipe_data import PROJECT, download, save_json


BASE_URL = "https://apis.data.go.kr/B554287/NationalWelfareInformationsV001"
SERVICE_IDS = (
    "WLF00003191",  # 노인맞춤돌봄서비스
    "WLF00001093",  # 독거노인·장애인 응급안전안심서비스
    "WLF00001164",  # 기초연금
    "WLF00001155",  # 노인일자리 및 사회활동 지원사업
    "WLF00000072",  # 에너지바우처
    "WLF00000055",  # 통합문화이용권
)


def request_xml(operation, api_key, parameters):
    query = urlencode({"serviceKey": unquote(api_key), **parameters})
    content, _ = download(f"{BASE_URL}/{operation}?{query}")
    root = ET.fromstring(content)
    if root.findtext("resultCode") != "0":
        raise ValueError("복지 API 인증·요청 오류입니다. 키와 활용신청 상태를 확인해 주세요.")
    return root


def clean_text(value):
    value = unescape(unescape(value or ""))
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\n{3,}", "\n\n", value.replace("\r", "\n")).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    api_key = load_api_key("WELFARE_API_KEY")
    if not api_key:
        parser.error("루트 .env 또는 환경변수에 WELFARE_API_KEY를 설정해 주세요.")
    try:
        entries = {}
        page = 1
        while True:
            root = request_xml("NationalWelfarelistV001", api_key, {
                "callTp": "L", "pageNo": page, "numOfRows": 500,
                "srchKeyCode": "001", "orderBy": "popular",
            })
            batch = root.findall("servList")
            if not batch:
                raise ValueError("복지 API 목록이 비어 있습니다.")
            for node in batch:
                fields = {child.tag: clean_text(child.text) for child in node}
                service_id = fields.get("servId", "")
                if not re.fullmatch(r"WLF[0-9]+", service_id) or service_id in entries:
                    raise ValueError("복지 서비스 ID 누락 또는 페이지 중복입니다.")
                entries[service_id] = fields
            if len(entries) >= int(root.findtext("totalCount", "0")):
                break
            page += 1
            if page > 1000:
                raise ValueError("복지 API 페이지 제한을 초과했습니다.")
        selected = []
        for service_id in SERVICE_IDS:
            if service_id not in entries:
                raise ValueError("시연 대상 복지 서비스가 API 목록에 없습니다.")
            row = dict(entries[service_id])
            details = request_xml("NationalWelfaredetailedV001", api_key, {
                "callTp": "D", "servId": service_id,
            })
            if details.findtext("servId") != service_id:
                raise ValueError("복지 서비스 상세 ID가 일치하지 않습니다.")
            for field in ("tgtrDtlCn", "slctCritCn", "alwServCn", "crtrYr"):
                row[field] = clean_text(details.findtext(field))
            if not row.get("servNm") or not row["tgtrDtlCn"]:
                raise ValueError("복지 사업명 또는 지원대상 내용이 없습니다.")
            link = urlsplit(row.get("servDtlLink", ""))
            if link.scheme != "https" or link.hostname not in ("www.bokjiro.go.kr", "bokjiro.go.kr"):
                raise ValueError("공식 복지로 링크가 올바르지 않습니다.")
            selected.append(row)
        save_json(PROJECT / "assets/data/welfare_services.json", selected)
        save_json(PROJECT / "assets/data/welfare_source.json", {
            "provider": "한국사회보장정보원 / 복지로",
            "endpoint": BASE_URL,
            "guideVersion": "2.2",
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "catalogCount": len(entries),
            "count": len(selected),
            "scope": "central_nationwide",
        })
    except HTTPError as error:
        parser.exit(1, f"복지 API HTTP 오류({error.code}). 기존 JSON을 유지합니다.\n")
    except (URLError, TimeoutError):
        parser.exit(1, "복지 API 연결에 실패했습니다. 기존 JSON을 유지합니다.\n")
    except (ET.ParseError, ValueError, OSError):
        # Do not echo upstream messages or request URLs containing serviceKey.
        parser.exit(1, "복지 API 응답 검증 또는 저장에 실패했습니다. 키·활용신청 상태와 응답을 확인해 주세요.\n")
    print(f"복지 API 목록 {len(entries)}건 확인 → 어르신 관련 {len(selected)}종 상세 저장")


if __name__ == "__main__":
    main()
