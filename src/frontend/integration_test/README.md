# 영양분석 실제 API 통합 시험

`nutrition_api_test.dart`와 `../test/live_nutrition_api_test.dart`는 같은 검사를 Android와 헤드리스 Flutter에서 실행한다. 서버 응답을 대체하지 않고 실제 `Account`, `Dio`, `IntakeApi`, `AiApi`를 사용한다. 기기의 기존 로그인 정보를 건드리지 않도록 시험의 로컬 저장소만 메모리에 둔다.

빈 **시험용 PostgreSQL DB**를 준비하고, 백엔드 `DATABASE_URL`을 그 DB로 지정한다. 아래 명령은 `src/backend`에서 실행한다. 운영 DB에는 시험 fixture를 적재하지 않는다.

```powershell
uv run --locked alembic upgrade head
uv run --locked python -m app.jobs.import_public_data --dataset nutrition --nutrition ../frontend/integration_test/fixtures/nutrition_http.json --apply
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 18082
```

fixture에는 합성 식품 5개만 있으며 쌀밥은 100g당 150kcal, 1회 분량 200g으로 설정했다. 모델의 영양 지식을 검증하는 자료가 아니다. 시험은 실수로 외부 서버를 대상으로 실행하지 않도록 localhost·127.0.0.1·10.0.2.2의 18082 포트만 허용한다. 새 게스트를 만들고 그 계정의 기록만 수정·삭제한다. 도중 실패한 실행의 합성 계정과 기록은 시험 DB에 남을 수 있다.

`src/frontend`에서 실제 HTTP 저장 경로를 실행한다. 이 명령은 Android 빌드를 수행하지 않으며, 기본 `flutter test`에서는 실제 서버가 필요한 두 시험을 실행하지 않는다.

```powershell
flutter test --no-pub test/live_nutrition_api_test.dart --dart-define=NUTRITION_QA_BASE_URL=http://127.0.0.1:18082
```

실제 NVIDIA 호출도 검사하려면 **시험 서버에만** `NVIDIA_AI_ENABLED=true`와 `NVIDIA_API_KEY`를 설정하고 위 명령에 `--dart-define=NUTRITION_QA_LIVE_AI=true`를 추가한다. 공개 음식 이미지와 일반 음식명만 전송한다. 제공자 오류·시간 초과는 시험 실패로 유지하며 가짜 성공 응답으로 대체하지 않는다. 키를 Dart 옵션이나 APK에 넣지 않는다.

헤드리스 화면의 참고 이미지는 `NUTRITION_QA_SCREENSHOT_DIR`에 매번 새로운 빈 절대 경로를 지정하면 저장한다. 한글 시험 글꼴은 로컬 `.ttf` 파일의 절대 경로를 `NUTRITION_QA_FONT_FILE`로 지정한다. 이 이미지는 Android 기본 글꼴·아이콘이나 카메라 권한 검증을 대신하지 않는다.

Android 에뮬레이터에서는 다음 명령을 사용한다. `10.0.2.2`는 에뮬레이터에서 호스트 로컬 API를 가리킨다. 기존 driver가 화면을 `build/screenshots`에 저장하므로 매번 실행 후 별도 실행 폴더로 보존한다.

```powershell
flutter drive --driver=test_driver/integration_test.dart --target=integration_test/nutrition_api_test.dart -d emulator-5554 --dart-define=NUTRITION_QA_BASE_URL=http://10.0.2.2:18082 --dart-define=NUTRITION_QA_LIVE_AI=true
```

검사 범위는 유사 후보의 명시 선택, 반 인분 계산, 서버 커밋 뒤 응답 유실 주입, 같은 저장 키 재전송, 실제 목록·상세·분량 수정·다른 계정 차단·삭제, 별도의 실제 NVIDIA 사진/재료 응답 해석이다. 유사 후보 UI의 시작 인식 결과는 반복 가능한 합성 입력이다. 실제 사진 촬영·앨범 선택의 OS 동작과 실제 사용자 사용성은 기기에서 별도 확인한다.
