import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/data/guest_session.dart';
import 'package:valueflow/data/recipe_api.dart';
import 'package:valueflow/data/recipe_library_api.dart';
import 'package:valueflow/models/recipe_record.dart';
import 'package:valueflow/models/shopping_list.dart';
import 'package:valueflow/screens/recipe_library_screens.dart';
import 'package:valueflow/screens/shopping_list_screen.dart';
import 'package:valueflow/services/settings.dart';

class _ShoppingServer {
  _ShoppingServer() {
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          requests.add(options);
          Object? data;
          if (options.path == '/api/v1/auth/guest') {
            data = {'access_token': List.filled(43, 'a').join()};
          } else {
            expect(options.headers['Authorization'], startsWith('Bearer '));
            expect(options.followRedirects, isFalse);
            if (options.path.contains('/meal-plans/')) {
              data = {'items': []};
            } else if (options.method == 'PATCH') {
              if (failNext != null) {
                final status = failNext!;
                failNext = null;
                if (status == 409) {
                  hash = List.filled(64, 'c').join();
                  amount = '450 g';
                  checked = false;
                }
                handler.reject(
                  DioException(
                    requestOptions: options,
                    type: DioExceptionType.badResponse,
                    response: Response(
                      requestOptions: options,
                      statusCode: status,
                      data: {
                        'error': {
                          'message': status == 409
                              ? '목록이 바뀌었어요. 다시 확인해 주세요.'
                              : '저장에 실패했어요.',
                        },
                      },
                    ),
                  ),
                );
                return;
              }
              expect(options.data, {'source_hash': hash, 'checked': !checked});
              checked = options.data['checked'] as bool;
              data = {'item_key': key, 'source_hash': hash, 'checked': checked};
            } else {
              data = {
                'items': empty ? [] : [item],
                'warnings': [],
              };
            }
          }
          handler.resolve(
            Response(
              requestOptions: options,
              statusCode: 200,
              data: {'data': data},
            ),
          );
        },
      ),
    );
    client = ApiClient(dio: dio);
    library = RecipeLibraryApi(client, GuestSession(client));
  }

  final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
  final requests = <RequestOptions>[];
  final key = List.filled(64, 'a').join();
  String hash = List.filled(64, 'b').join(), amount = '300 g';
  int? failNext;
  bool checked = false, empty = false;
  late final ApiClient client;
  late final RecipeLibraryApi library;

  Map<String, dynamic> get item => {
    'item_key': key,
    'source_hash': hash,
    'name': '쌀',
    'amount_text': amount,
    'checked': checked,
    'shopping_search_url': Uri.https('www.coupang.com', '/np/search', {
      'q': '쌀',
    }).toString(),
    'sources': [
      {
        'meal_slot': 'breakfast',
        'recipe_name': '쌀죽',
        'name_raw': '쌀',
        'amount_text': '100g',
        'section': null,
      },
    ],
  };
}

Future<void> _pump(WidgetTester tester, Widget home) async {
  tester.view.physicalSize = const Size(320, 720);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: const TextScaler.linear(1.4)),
        child: child!,
      ),
      home: home,
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  test(
    'shopping URLs allow only the exact ingredient search on HTTPS Coupang',
    () {
      final server = _ShoppingServer();
      expect(ShoppingItem.fromJson(server.item).shoppingUrl?.queryParameters, {
        'q': '쌀',
      });
      for (final url in [
        'http://www.coupang.com/np/search?q=쌀',
        'https://evil.test/np/search?q=쌀',
        'https://user@www.coupang.com/np/search?q=쌀',
        'https://www.coupang.com/other?q=쌀',
        'https://www.coupang.com/np/search?q=쌀&profile=private',
        'https://www.coupang.com/np/search?q=다른재료',
      ]) {
        expect(
          ShoppingItem.fromJson({
            ...server.item,
            'shopping_search_url': url,
          }).shoppingUrl,
          isNull,
        );
      }
      const ingredient = RecipeIngredientItem(
        orderNo: 1,
        section: null,
        name: '간장',
        nameRaw: '간장 & 소금',
        amountText: '1큰술',
      );
      expect(ingredient.shoppingUrl.queryParameters, {'q': '간장 & 소금'});
      expect(ingredient.shoppingUrl.host, 'www.coupang.com');
    },
  );

  testWidgets('day plan opens the shopping screen for its selected date', (
    tester,
  ) async {
    final server = _ShoppingServer();
    await _pump(
      tester,
      MealPlanScreen(
        library: server.library,
        recipes: RecipeApi(server.client),
        settings: AppSettings(),
      ),
    );
    await tester.tap(find.byKey(const Key('plan-shopping-start')));
    await tester.pumpAndSettle();
    expect(find.text('장보기 목록'), findsOneWidget);
    expect(server.requests.last.path, contains('/api/v1/shopping-lists/'));
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'large text can check, reopen, uncheck, and read original amounts',
    (tester) async {
      final server = _ShoppingServer();
      final screen = ShoppingListScreen(
        library: server.library,
        date: DateTime(2026, 11, 20),
      );
      await _pump(tester, screen);
      expect(find.text('300 g'), findsOneWidget);
      final checkbox = find.byType(CheckboxListTile);
      await tester.ensureVisible(checkbox);
      await tester.tap(checkbox);
      await tester.pumpAndSettle();
      expect(server.checked, isTrue);
      expect(tester.widget<CheckboxListTile>(checkbox).value, isTrue);
      await _pump(
        tester,
        ShoppingListScreen(
          key: const Key('reopen'),
          library: server.library,
          date: DateTime(2026, 11, 20),
        ),
      );
      expect(tester.widget<CheckboxListTile>(checkbox).value, isTrue);
      await tester.ensureVisible(checkbox);
      await tester.tap(checkbox);
      await tester.pumpAndSettle();
      expect(server.checked, isFalse);
      final source = find.text('메뉴별 원문 분량 보기');
      await tester.ensureVisible(source);
      await tester.tap(source);
      await tester.pumpAndSettle();
      expect(find.text('아침 · 쌀죽\n쌀 100g'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('failed checks keep the old state and stale lists reload', (
    tester,
  ) async {
    final server = _ShoppingServer();
    await _pump(
      tester,
      ShoppingListScreen(library: server.library, date: DateTime(2026, 11, 20)),
    );
    final checkbox = find.byType(CheckboxListTile);
    server.failNext = 503;
    await tester.ensureVisible(checkbox);
    await tester.tap(checkbox);
    await tester.pumpAndSettle();
    expect(tester.widget<CheckboxListTile>(checkbox).value, isFalse);
    expect(find.text('저장에 실패했어요.'), findsOneWidget);
    server.failNext = 409;
    await tester.tap(checkbox);
    await tester.pumpAndSettle();
    expect(find.text('450 g'), findsOneWidget);
    expect(tester.widget<CheckboxListTile>(checkbox).value, isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets('external browser failure is explained without changing checks', (
    tester,
  ) async {
    const channel = MethodChannel('plugins.flutter.io/url_launcher');
    var attempts = 0;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
      call,
    ) async {
      attempts++;
      expect(call.method, 'launch');
      expect((call.arguments as Map)['headers'], isEmpty);
      return false;
    });
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        null,
      ),
    );
    final server = _ShoppingServer();
    await _pump(
      tester,
      ShoppingListScreen(library: server.library, date: DateTime(2026, 11, 20)),
    );
    final button = find.byKey(Key('shopping-link-${server.key}'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(attempts, 1);
    expect(find.text('연결할 수 없어요. 인터넷 연결과 브라우저를 확인해 주세요.'), findsOneWidget);
    expect(server.checked, isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets('empty shopping lists explain the next step', (tester) async {
    final server = _ShoppingServer()..empty = true;
    await _pump(
      tester,
      ShoppingListScreen(library: server.library, date: DateTime(2026, 11, 20)),
    );
    expect(find.byType(CheckboxListTile), findsNothing);
    expect(find.textContaining('식단에 메뉴를 담으면 재료가 보여요.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
