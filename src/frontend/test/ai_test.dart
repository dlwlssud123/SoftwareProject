import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/ai_api.dart';
import 'package:valueflow/data/auth_api.dart';
import 'package:valueflow/data/profile_api.dart';
import 'package:valueflow/screens/assistant_screen.dart';
import 'package:valueflow/services/account.dart';
import 'package:valueflow/services/settings.dart';

class _Storage implements FlutterSecureStorage {
  @override
  dynamic noSuchMethod(Invocation invocation) => Future<void>.value();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Account account;
  late AiApi api;
  late List<RequestOptions> sent;
  late Completer<void>? barrier;
  late bool broken;
  setUp(() {
    sent = [];
    barrier = null;
    broken = false;
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (request, handler) async {
          sent.add(request);
          if (barrier != null) await barrier!.future;
          handler.resolve(
            Response(
              requestOptions: request,
              statusCode: 200,
              data: {
                'data': request.path.endsWith('/food-ingredients')
                    ? {
                        'ingredients': [
                          {
                            'name': '양파',
                            'amount_g': 50,
                            'matches': [],
                            'is_water': false,
                          },
                        ],
                        'notice': '1인분 예상 재료예요.',
                        'reference_recipe': null,
                      }
                    : broken
                    ? {'answer': 7}
                    : {'answer': '밥과 반찬을 골고루 드세요.'},
              },
            ),
          );
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
    'AI request uses service auth, bounded timeout, consent and only entered message',
    () async {
      expect(await api.chat(' 점심 요리 ', CancelToken()), contains('밥'));
      final request = sent.single;
      expect(request.data, {
        'message': '점심 요리',
        'allow_external_processing': true,
      });
      expect(request.headers['Authorization'], startsWith('Bearer '));
      expect(request.followRedirects, isFalse);
      expect(request.receiveTimeout, const Duration(seconds: 40));
    },
  );
  test(
    'ingredient request sends only dish name, serving suggestion and consent',
    () async {
      final result = await api.ingredients('양파요리', 200, CancelToken());
      expect(result.ingredients.single.name, '양파');
      expect(result.ingredients.single.grams, 50);
      final request = sent.single;
      expect(request.path, '/api/v1/ai/food-ingredients');
      expect(request.data, {
        'dish_name': '양파요리',
        'standard_serving_grams': 200,
        'allow_external_processing': true,
      });
      expect(request.headers['Authorization'], startsWith('Bearer '));
      expect(request.followRedirects, isFalse);
    },
  );
  test('signed-out or oversized photo never reaches network', () async {
    expect(
      () => api.photo(Uint8List(2 * 1024 * 1024 + 1), CancelToken()),
      throwsA(isA<ApiException>()),
    );
    account.session = null;
    await expectLater(
      api.chat('요리', CancelToken()),
      throwsA(isA<ApiException>()),
    );
    expect(sent, isEmpty);
  });
  test('malformed AI answer is a visible API error', () async {
    broken = true;
    await expectLater(
      api.chat('요리', CancelToken()),
      throwsA(isA<ApiException>()),
    );
  });
  test('account change during AI request discards old answer', () async {
    barrier = Completer<void>();
    final response = api.chat('요리', CancelToken());
    await Future<void>.delayed(Duration.zero);
    account.session = null;
    barrier!.complete();
    await expectLater(response, throwsA(isA<ApiException>()));
  });
  testWidgets(
    'chat requires consent and suppresses duplicate sends while waiting',
    (tester) async {
      barrier = Completer<void>();
      await tester.pumpWidget(
        MaterialApp(
          home: ConversationScreen(settings: AppSettings(), api: api),
        ),
      );
      await tester.enterText(find.byType(TextField), '점심 요리');
      await tester.tap(find.byTooltip('질문 보내기'));
      await tester.pumpAndSettle();
      expect(sent, isEmpty);
      expect(find.text('동의하고 이용'), findsOneWidget);
      await tester.tap(find.text('동의하고 이용'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(sent, hasLength(1));
      expect(
        tester
            .widget<IconButton>(
              find.byWidgetPredicate(
                (w) => w is IconButton && w.tooltip == '질문 보내기',
              ),
            )
            .onPressed,
        isNull,
      );
      barrier!.complete();
      await tester.pumpAndSettle();
      expect(find.text('밥과 반찬을 골고루 드세요.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
