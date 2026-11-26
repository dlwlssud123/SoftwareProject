import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/ai_api.dart';
import 'package:valueflow/data/auth_api.dart';
import 'package:valueflow/data/profile_api.dart';
import 'package:valueflow/models/welfare_chat.dart';
import 'package:valueflow/screens/welfare_chat_screen.dart';
import 'package:valueflow/services/account.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/theme.dart';

class _Storage implements FlutterSecureStorage {
  @override
  dynamic noSuchMethod(Invocation invocation) => Future<void>.value();
}

Map<String, dynamic> answer() => {
  'answer': '공식 자료에서 지원 내용을 확인해 보세요. [1]',
  'notice': '실제 지원 대상 여부는 담당 기관에서 확인해 주세요.',
  'answer_status': 'generated',
  'evidence_status': 'weak',
  'region': null,
  'district': null,
  'notes': <String>[],
  'sources': [
    {
      'number': 1,
      'title': '안부 확인 지원',
      'excerpt': '지원 대상과 신청 방법은 주민센터에서 확인하세요.',
      'url': 'https://www.bokjiro.go.kr/ssis-tbu/',
      'checked_at': '2026-11-18T00:00:00Z',
    },
  ],
};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late AiApi api;
  late Account account;
  late List<RequestOptions> requests;
  late bool failed;
  setUp(() {
    requests = [];
    failed = false;
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (request, handler) {
          requests.add(request);
          if (failed) {
            handler.reject(
              DioException(
                requestOptions: request,
                type: DioExceptionType.badResponse,
                response: Response(
                  requestOptions: request,
                  statusCode: 503,
                  data: {
                    'error': {
                      'code': 'RAG_NOT_CONFIGURED',
                      'message': '복지 자료 검색을 준비 중이에요.',
                      'retryable': true,
                      'fields': [],
                    },
                  },
                ),
              ),
            );
          } else {
            handler.resolve(
              Response(
                requestOptions: request,
                statusCode: 200,
                data: {'data': answer()},
              ),
            );
          }
        },
      ),
    );
    final client = ApiClient(dio: dio);
    account =
        Account(
            AuthApi(client),
            _Storage(),
            profiles: ProfileApi(client),
            serverUrl: 'https://example.test',
            kakaoEnabled: false,
          )
          ..session = ServiceSession(
            userId: 'owner',
            token: List.filled(43, 'a').join(),
            expiresAt: DateTime.utc(2030),
            kakaoLinked: false,
          );
    api = AiApi(client, account);
  });

  test(
    'welfare request sends entered question and explicit region only',
    () async {
      final result = await api.welfareChat(
        ' 난방비 지원 ',
        CancelToken(),
        region: '대구',
        district: '남구',
      );
      expect(requests.single.path, '/api/v1/ai/welfare-chat');
      expect(requests.single.data, {
        'message': '난방비 지원',
        'region': '대구',
        'district': '남구',
        'allow_external_processing': true,
      });
      expect(requests.single.headers['Authorization'], startsWith('Bearer '));
      expect(result.sources.single.title, '안부 확인 지원');
      expect(result.sources.single.url!.host, 'www.bokjiro.go.kr');
    },
  );

  test(
    'national question omits location and owner changes invalidate response',
    () async {
      await api.welfareChat('지원 안내', CancelToken());
      expect(requests.single.data, {
        'message': '지원 안내',
        'allow_external_processing': true,
      });
      account.session = null;
      await expectLater(
        api.welfareChat('지원 안내', CancelToken()),
        throwsA(isA<ApiException>()),
      );
      expect(requests, hasLength(1));
    },
  );

  test('untrusted source links and invented statuses are rejected', () {
    for (final url in [
      'javascript:alert(1)',
      'https://example.test',
      'https://bokjiro.go.kr.example.test',
    ]) {
      final value = answer();
      (value['sources'] as List).single['url'] = url;
      expect(() => WelfareChatAnswer.fromJson(value), throwsFormatException);
    }
    expect(
      () =>
          WelfareChatAnswer.fromJson({...answer(), 'answer_status': 'unknown'}),
      throwsFormatException,
    );
    expect(
      () => WelfareChatAnswer.fromJson({...answer(), 'sources': <dynamic>[]}),
      throwsFormatException,
    );
  });

  Future<void> show(WidgetTester tester, {bool large = false}) async {
    if (large) {
      tester.view.physicalSize = const Size(320, 720);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
    }
    await tester.pumpWidget(
      MaterialApp(
        theme: appTheme(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: TextScaler.linear(large ? 1.8 : 1)),
          child: child!,
        ),
        home: WelfareChatScreen(api: api, settings: AppSettings()),
      ),
    );
  }

  Future<void> send(WidgetTester tester) async {
    await tester.enterText(
      find.byKey(const Key('rag-question')),
      '난방비 지원이 있나요?',
    );
    await tester.scrollUntilVisible(
      find.byKey(const Key('rag-send')),
      200,
      scrollable: find
          .descendant(
            of: find.byType(ListView),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.tap(find.byKey(const Key('rag-send')));
    await tester.pumpAndSettle();
  }

  testWidgets(
    'declining external processing sends nothing and preserves question',
    (tester) async {
      await show(tester);
      await send(tester);
      expect(requests, isEmpty);
      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();
      expect(requests, isEmpty);
      expect(find.text('난방비 지원이 있나요?'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'answer keeps source, checked date and weak-evidence warning visible',
    (tester) async {
      await show(tester);
      await send(tester);
      await tester.tap(find.text('동의하고 이용'));
      await tester.pumpAndSettle();
      expect(requests, hasLength(1));
      await tester.scrollUntilVisible(
        find.text('[1] 안부 확인 지원'),
        250,
        scrollable: find
            .descendant(
              of: find.byType(ListView),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      expect(find.text('자료 확인: 2026-11-18'), findsOneWidget);
      expect(find.text('공식 안내 열기'), findsOneWidget);
      expect(find.textContaining('질문과 꼭 맞는 자료가 아닐 수 있어요.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'unavailable service shows actionable error and never a fake answer',
    (tester) async {
      failed = true;
      await show(tester);
      await send(tester);
      await tester.tap(find.text('동의하고 이용'));
      await tester.pumpAndSettle();
      expect(find.text('복지 자료 검색을 준비 중이에요.'), findsOneWidget);
      expect(find.text('공식 안내 열기'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('welfare form and citations fit 320px at 180 percent text', (
    tester,
  ) async {
    await show(tester, large: true);
    await send(tester);
    await tester.tap(find.text('동의하고 이용'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('공식 안내 열기'),
      300,
      scrollable: find
          .descendant(
            of: find.byType(ListView),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.pumpAndSettle();
    expect(find.text('공식 안내 열기').hitTestable(), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
