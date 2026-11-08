# 레시피 외부 원문 대조·보완 결과

> `python -m agetech_data.recipes.correct`로 생성합니다. 수집 원본은 변경하지 않습니다.

- 수집 원본 SHA-256: `d5db8e9435fe667902790df87b621ee88d88e40732a8a8128ea6e2dc62cfb354`
- 보완 목록 SHA-256: `a65aa83fad372106822faf4671ed37829841df69f637d339fa8d64dbf3d1e6e0`
- 원본/보완본 단계 수: 213 → 217
- 누락 단계: 4 → 0
- 품질 상태: `{'ok': 37, 'flagged': 11, 'hold': 2}` → `{'ok': 40, 'flagged': 10, 'hold': 0}`

| 레시피 ID | 항목 | 구분 | 확인일 | 근거 |
|---|---|---|---|---|
| 33 | `MANUAL01` | official_source | 2026-11-04 | [공식 원문](https://www.foodsafetykorea.go.kr/portal/cookrcp/cookrcpInfoDtl.do?menu_grp=MENU_NEW03&menu_no=3608&rcp_seq=33) |
| 33 | `MANUAL04` | official_source | 2026-11-04 | [공식 원문](https://www.foodsafetykorea.go.kr/portal/cookrcp/cookrcpInfoDtl.do?menu_grp=MENU_NEW03&menu_no=3608&rcp_seq=33) |
| 36 | `MANUAL01` | official_source | 2026-11-04 | [공식 원문](https://www.foodsafetykorea.go.kr/portal/cookrcp/cookrcpInfoDtl.do?menu_grp=MENU_NEW03&menu_no=3608&rcp_seq=36) |
| 36 | `MANUAL02` | official_source | 2026-11-04 | [공식 원문](https://www.foodsafetykorea.go.kr/portal/cookrcp/cookrcpInfoDtl.do?menu_grp=MENU_NEW03&menu_no=3608&rcp_seq=36) |
| 642 | `RCP_PARTS_DTLS` | format_only | 2026-11-04 | [공식 원문](https://www.foodsafetykorea.go.kr/portal/cookrcp/cookrcpInfoDtl.do?menu_grp=MENU_NEW03&menu_no=3608&rcp_seq=642) |
| 276 | `RCP_PARTS_DTLS` | format_only | 2026-11-04 | [공식 원문](https://www.foodsafetykorea.go.kr/portal/cookrcp/cookrcpInfoDtl.do?menu_grp=MENU_NEW03&menu_no=3608&rcp_seq=276) |

## 남은 확인 항목

- ID 38의 표고버섯 기둥 분량은 공식 상세·배포 자료에도 수치가 없어 미확정으로 유지합니다.
- `INFO_WGT` 47건 누락은 조리 후 중량 근거 없이 재료 합계로 대체하지 않습니다.
- 괄호 보완은 기존 재료·수치에 닫는 괄호만 추가하는 표기 수정입니다. 공식 원문에도 같은 표기 오류가 있습니다.
- 보완본은 `data/processed/recipes_corrected.json`, 상세 감사 기록은 `recipe_correction_audit.json`입니다.
- Flutter 앱도 같은 보완 목록을 읽습니다. upstream 값이 다른 내용으로 바뀌면 덮어쓰지 않고 재검증 오류를 냅니다.

## 외부 자료의 불일치

ID 38의 나트륨은 식품안전나라 원문에서 2441mg이지만 교육부 배포 가이드에서는 244mg입니다. 누락 보완 범위를 넘어서는 수치 불일치이므로 현재 값을 임의로 변경하지 않고 검토 대상으로 남깁니다.
- [식품안전나라 상세](https://www.foodsafetykorea.go.kr/portal/cookrcp/cookrcpInfoDtl.do?menu_grp=MENU_NEW03&menu_no=3608&rcp_seq=38)
- [교육부 학교급식 나트륨 줄이기 가이드, 인쇄 50쪽](https://clik.nanet.go.kr/clikr-collection/policyinfo/202/1010/2014/CLIKC6983894526481553_attach_1.pdf)
