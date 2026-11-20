import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/auth_api.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/data/profile_api.dart';
import 'package:valueflow/data/welfare_api.dart';
import 'package:valueflow/models/welfare.dart';
import 'package:valueflow/screens/welfare_screens.dart';
import 'package:valueflow/services/account.dart';
import 'package:valueflow/services/settings.dart';

class _Storage implements FlutterSecureStorage {
  @override
  dynamic noSuchMethod(Invocation invocation) {
    if (invocation.memberName == #delete) return Future<void>.value();
    return super.noSuchMethod(invocation);
  }
}

ServiceSession _session(String user) => ServiceSession(
  userId: user,
  token: 'fixture-session',
  expiresAt: DateTime.utc(2030),
  kakaoLinked: true,
);

class _Server {
  _Server() {
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    client = ApiClient(dio: dio);
    account = Account(
      AuthApi(client),
      _Storage(),
      profiles: ProfileApi(client),
      serverUrl: 'https://example.test',
      kakaoEnabled: false,
    )..session = _session('owner');
    api = WelfareApi(client, account);
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          requests.add(options);
          final path = options.path;
          final private = path.startsWith('/api/v1/saved-welfare');
          void fail(int status, String code) => handler.reject(
            DioException(
              requestOptions: options,
              type: DioExceptionType.badResponse,
              response: Response(
                requestOptions: options,
                statusCode: status,
                data: {
                  'error': {
                    'code': code,
                    'message': code,
                    'retryable': status >= 500,
                  },
                },
              ),
            ),
          );
          if (expire && private) {
            fail(401, 'AUTH_REQUIRED');
            return;
          }
          if (failNotes &&
              path.endsWith('/note') &&
              options.method == 'PATCH') {
            fail(503, 'SAVED_WELFARE_UNAVAILABLE');
            return;
          }
          Object? data;
          if (path.endsWith('/recommendations')) {
            if (failSearch) {
              fail(503, 'WELFARE_UNAVAILABLE');
              return;
            }
            data = {
              'items': empty
                  ? []
                  : [
                      {
                        'item': service,
                        'reasons': ['거주 지역 관련 사업'],
                      },
                    ],
              'warnings': ['지원 자격과 신청 가능 여부는 공식 안내에서 확인해 주세요.'],
            };
          } else if (path == '/api/v1/welfare/WLF123') {
            if (withdrawn) {
              fail(404, 'WELFARE_NOT_FOUND');
              return;
            }
            data = service;
          } else if (path == '/api/v1/saved-welfare') {
            data = {
              'items': saved
                  ? [
                      {
                        'service_id': 'WLF123',
                        'title': withdrawn ? null : '식사 지원',
                      },
                    ]
                  : [],
              'total': saved ? 1 : 0,
            };
          } else if (path.endsWith('/note')) {
            if (!saved) {
              fail(404, 'SAVED_WELFARE_NOT_FOUND');
              return;
            }
            if (options.method == 'PATCH') {
              note = options.data['note'] as String?;
            }
            data = {
              'service_id': 'WLF123',
              'note': note,
              'updated_at': '2026-11-19T23:50:00Z',
            };
          } else if (private) {
            if (options.method == 'PUT') saved = true;
            if (options.method == 'DELETE') {
              saved = false;
              note = null;
            }
            data = {'saved': saved};
          } else {
            throw StateError('Unexpected test route');
          }
          afterResponse?.call();
          handler.resolve(
            Response(
              requestOptions: options,
              statusCode: options.method == 'DELETE' ? 204 : 200,
              data: jsonDecode(jsonEncode({'data': data})),
            ),
          );
        },
      ),
    );
  }
  late final ApiClient client;
  late final Account account;
  late final WelfareApi api;
  final requests = <RequestOptions>[];
  bool saved = false,
      withdrawn = false,
      expire = false,
      failNotes = false,
      failSearch = false,
      empty = false;
  String? note;
  void Function()? afterResponse;
  final service = <String, dynamic>{
    'service_id': 'WLF123',
    'title': '식사 지원',
    'summary': '지역 어르신 식사를 도와드려요.',
    'target_text': '만 65세 이상 등 세부 기준 확인',
    'selection_text': '소득 등 공식 기준 문의',
    'benefit_text': '식사 지원 안내',
    'ctpv': '서울특별시',
    'sgg': '강남구',
    'application': [
      {'method': '방문', 'description': '주민센터 문의 후 방문'},
    ],
    'contacts': [
      {'name': '주민센터', 'contact': '대표 전화 문의'},
    ],
    'quality_status': 'ok',
    'source': {
      'source_url': 'https://www.bokjiro.go.kr/service',
      'checked_at': '2026-11-19T23:50:00Z',
      'detail_checked_at': null,
    },
  };
}

Future<void> _show(WidgetTester tester, Widget child) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData(useMaterial3: true),
      builder: (_, child) => MediaQuery(
        data: const MediaQueryData(
          size: Size(800, 600),
          textScaler: TextScaler.linear(1.4),
        ),
        child: child!,
      ),
      home: child,
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('추천은 필요한 조건만 전달하며 저장·인증·다른 개인정보를 보내지 않는다', () async {
    final server = _Server();
    final results = await server.api.recommend(
      age: 70,
      region: '서울특별시',
      district: ' 강남구 ',
      livesAlone: true,
    );
    expect(results.items.single.service.id, 'WLF123');
    final request = server.requests.single;
    expect(request.data, {
      'age': 70,
      'region': '서울특별시',
      'district': '강남구',
      'lives_alone': true,
      'limit': 10,
    });
    expect(request.headers.containsKey('Authorization'), false);
    expect(request.followRedirects, false);
  });

  test('공식 HTTPS 정부 주소만 열고 확인일은 한국 시간으로 표시한다', () {
    final server = _Server();
    for (final url in [
      'http://www.bokjiro.go.kr/x',
      'https://evil.test/x',
      'https://bokjiro.go.kr.evil.test/x',
      'https://fixture@www.bokjiro.go.kr/x',
      'https://www.bokjiro.go.kr:8443/x',
      'javascript:alert(1)',
    ]) {
      final service = WelfareService.fromJson({
        ...server.service,
        'source': {...server.service['source'], 'source_url': url},
      });
      expect(service.officialUrl, isNull);
    }
    final service = WelfareService.fromJson(server.service);
    expect(service.officialUrl?.host, 'www.bokjiro.go.kr');
    expect(welfareDate(service.checkedAt), '2026.11.20 (한국 시간)');
  });

  test('같은 계정으로 저장·메모·해제를 처리하고 메모 빈 값은 null로 지운다', () async {
    final server = _Server();
    expect(await server.api.isSaved('WLF123'), false);
    expect(await server.api.save('WLF123'), true);
    expect(
      (await server.api.updateNote('WLF123', '  주민센터 문의함  ')).text,
      '주민센터 문의함',
    );
    expect((await server.api.note('WLF123')).text, '주민센터 문의함');
    expect((await server.api.saved()).items.single.title, '식사 지원');
    expect((await server.api.updateNote('WLF123', '   ')).text, isNull);
    await server.api.remove('WLF123');
    expect(server.saved, false);
    expect(
      server.requests.every(
        (r) => r.headers['Authorization'] == 'Bearer fixture-session',
      ),
      true,
    );
    expect(server.requests.every((r) => !r.followRedirects), true);
  });

  test('로그인 만료 후 재시도해도 새 게스트를 생성하지 않는다', () async {
    final server = _Server()..expire = true;
    await expectLater(
      server.api.saved(),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 401)),
    );
    expect(server.account.session, isNull);
    await expectLater(server.api.saved(), throwsA(isA<ApiException>()));
    expect(server.requests.length, 1);
  });

  test('계정 전환 중 도착한 이전 사용자의 메모를 돌려주지 않는다', () async {
    final server = _Server()
      ..saved = true
      ..note = '이전 메모';
    server.afterResponse = () => server.account.session = _session('another');
    await expectLater(server.api.note('WLF123'), throwsA(isA<ApiException>()));
  });

  test('부정확한 서비스 경로를 서버에 요청하지 않는다', () async {
    final server = _Server();
    await expectLater(
      server.api.save('../profile'),
      throwsA(isA<ApiException>()),
    );
    expect(server.requests, isEmpty);
  });

  testWidgets('140% 글자에서도 간단한 조건으로 추천하고 상세·저장으로 이동한다', (tester) async {
    final server = _Server();
    await _show(tester, WelfareSearchScreen(api: server.api));
    await tester.enterText(find.byKey(const Key('welfare-age')), '70');
    await tester.enterText(find.byKey(const Key('welfare-district')), '강남구');
    await tester.scrollUntilVisible(
      find.byKey(const Key('find-welfare')),
      250,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('find-welfare')));
    await tester.pumpAndSettle();
    expect(find.text('식사 지원'), findsOneWidget);
    expect(find.textContaining('지원 자격과 신청 가능 여부'), findsOneWidget);
    await tester.tap(find.text('식사 지원'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const Key('welfare-save')),
      250,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('welfare-save')));
    await tester.pumpAndSettle();
    expect(server.saved, true);
    expect(find.byKey(const Key('welfare-note')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('메모 저장 실패에도 입력을 보존하고 재시도 후 서버 값을 표시한다', (tester) async {
    final server = _Server()
      ..saved = true
      ..note = '기존 메모'
      ..failNotes = true;
    await _show(tester, WelfareNoteScreen(api: server.api, id: 'WLF123'));
    expect(find.text('기존 메모'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('welfare-note-input')),
      '서류 확인함',
    );
    await tester.scrollUntilVisible(
      find.byKey(const Key('save-welfare-note')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('save-welfare-note')));
    await tester.pumpAndSettle();
    expect(find.text('서류 확인함'), findsOneWidget);
    expect(server.note, '기존 메모');
    server.failNotes = false;
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('save-welfare-note')).hitTestable());
    await tester.pumpAndSettle();
    expect(server.note, '서류 확인함');
    expect(tester.takeException(), isNull);
  });

  testWidgets('현재 상세가 내려간 저장 복지도 메모와 해제 경로를 유지한다', (tester) async {
    final server = _Server()
      ..saved = true
      ..withdrawn = true
      ..note = '전화해 보기';
    await _show(tester, SavedWelfareScreen(api: server.api));
    await tester.tap(find.text('현재 안내를 확인할 수 없는 복지'));
    await tester.pumpAndSettle();
    expect(find.textContaining('현재 안내를 확인할 수 없어요.'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('welfare-note')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('welfare-note')));
    await tester.pumpAndSettle();
    expect(find.text('전화해 보기'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('welfare-save')));
    await tester.pumpAndSettle();
    expect(find.text('이 복지에 남긴 내 메모도 함께 삭제돼요.'), findsOneWidget);
    await tester.tap(find.text('유지하기'));
    await tester.pumpAndSettle();
    expect(server.saved, true);
    await tester.tap(find.byKey(const Key('welfare-save')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장 해제'));
    await tester.pumpAndSettle();
    expect(server.saved, false);
    expect(server.note, isNull);
  });

  testWidgets('검색 오류를 재시도해도 예시 결과로 대체하지 않고 빈 결과를 안내한다', (tester) async {
    final server = _Server()..failSearch = true;
    await _show(tester, WelfareSearchScreen(api: server.api));
    await tester.enterText(find.byKey(const Key('welfare-age')), '70');
    await tester.scrollUntilVisible(
      find.byKey(const Key('find-welfare')),
      250,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('find-welfare')));
    await tester.pumpAndSettle();
    expect(find.text('식사 지원'), findsNothing);
    server.failSearch = false;
    server.empty = true;
    await tester.tap(find.text('다시 불러오기'));
    await tester.pumpAndSettle();
    expect(find.textContaining('검색된 복지 정보가 없어요.'), findsOneWidget);
  });

  testWidgets('저장하지 않은 메모를 뒤로갈 때 유지 또는 폐기를 선택한다', (tester) async {
    final server = _Server()
      ..saved = true
      ..note = '서버 메모';
    await _show(
      tester,
      Builder(
        builder: (context) => Scaffold(
          body: FilledButton(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) =>
                    WelfareNoteScreen(api: server.api, id: 'WLF123'),
              ),
            ),
            child: const Text('메모 열기'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('메모 열기'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('welfare-note-input')), '수정 중');
    await tester.pumpAndSettle();
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('수정한 메모를 저장하지 않고 나갈까요?'), findsOneWidget);
    await tester.tap(find.text('계속 작성'));
    await tester.pumpAndSettle();
    expect(find.text('수정 중'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.text('나가기'));
    await tester.pumpAndSettle();
    expect(find.text('메모 열기'), findsOneWidget);
    expect(server.note, '서버 메모');
    expect(tester.takeException(), isNull);
  });

  testWidgets('실제 탭 구조의 Android 뒤로가기와 탭 재탭도 메모 폐기를 확인한다', (tester) async {
    final server = _Server()
      ..saved = true
      ..note = '서버 메모';
    final repository = await tester.runAsync(DemoRepository.load);
    await tester.pumpWidget(
      ValueFlowApp(
        repository: repository!,
        settings: AppSettings(persist: false),
        welfareApi: server.api,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('tab-2')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('복지 소식 · 맞춤 추천'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('saved-welfare')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('식사 지원'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const Key('welfare-note')),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('welfare-note')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('welfare-note-input')),
      '아직 저장하지 않음',
    );
    await tester.pumpAndSettle();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('수정한 메모를 저장하지 않고 나갈까요?'), findsOneWidget);
    await tester.tap(find.text('계속 작성'));
    await tester.pumpAndSettle();
    expect(find.text('아직 저장하지 않음'), findsOneWidget);
    await tester.tap(find.byKey(const Key('tab-2')));
    await tester.pumpAndSettle();
    expect(find.text('수정한 메모를 저장하지 않고 나갈까요?'), findsOneWidget);
    await tester.tap(find.text('나가기'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('welfare-note-input')), findsNothing);
    expect(server.note, '서버 메모');
    expect(tester.takeException(), isNull);
  });

  testWidgets('AI 도우미 탭에서 실제 복지 화면에 진입한다', (tester) async {
    final server = _Server();
    final repository = await tester.runAsync(DemoRepository.load);
    await tester.pumpWidget(
      ValueFlowApp(
        repository: repository!,
        settings: AppSettings(persist: false),
        welfareApi: server.api,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('tab-2')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('복지 소식 · 맞춤 추천'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('saved-welfare')), findsOneWidget);
    expect(find.byKey(const Key('welfare-age')), findsOneWidget);
  });
}
