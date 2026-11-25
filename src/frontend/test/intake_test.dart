import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/data/auth_api.dart';
import 'package:valueflow/data/intake_api.dart';
import 'package:valueflow/data/ai_api.dart';
import 'package:valueflow/data/profile_api.dart';
import 'package:valueflow/models/intake.dart';
import 'package:valueflow/models/ai.dart';
import 'package:valueflow/screens/photo_food_screen.dart';
import 'package:valueflow/screens/intake_screens.dart';
import 'package:valueflow/screens/ingredient_review_screen.dart';
import 'package:valueflow/services/account.dart';
import 'package:valueflow/services/settings.dart';

class _Storage implements FlutterSecureStorage {
  final values = <String, String>{};
  bool failWrite = false, failDelete = false;
  @override
  dynamic noSuchMethod(Invocation invocation) {
    final key = invocation.namedArguments[#key] as String;
    if (invocation.memberName == #read) {
      return Future<String?>.value(values[key]);
    }
    if (invocation.memberName == #write) {
      if (failWrite) {
        return Future<void>.error(Exception('private storage failure'));
      }
      values[key] = invocation.namedArguments[#value] as String;
      return Future<void>.value();
    }
    if (invocation.memberName == #delete) {
      if (failDelete) {
        return Future<void>.error(Exception('private delete failure'));
      }
      values.remove(key);
      return Future<void>.value();
    }
    return super.noSuchMethod(invocation);
  }
}

class _IngredientAi implements AiApi {
  _IngredientAi(this.respond);
  final Future<IngredientEstimate> Function() respond;
  int calls = 0;
  String? requestedName;
  int? requestedGrams;
  @override
  Future<IngredientEstimate> ingredients(
    String name,
    int grams,
    CancelToken token,
  ) {
    calls++;
    requestedName = name;
    requestedGrams = grams;
    return respond();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Server {
  _Server() {
    final dio = Dio(BaseOptions(baseUrl: origin));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          requests.add(options);
          final path = options.path.split('?').first;
          final private = path.startsWith('/api/v1/meals');
          if (private) {
            expect(options.headers['Authorization'], startsWith('Bearer '));
            expect(options.followRedirects, isFalse);
          }
          void fail(
            int status,
            String code, {
            List<Map<String, String>> fields = const [],
          }) {
            handler.reject(
              DioException(
                requestOptions: options,
                type: DioExceptionType.badResponse,
                response: Response(
                  requestOptions: options,
                  statusCode: status,
                  data: {
                    'error': {
                      'code': code,
                      'message': code == 'FOOD_REVISION_CHANGED'
                          ? '음식 정보가 바뀌었어요.'
                          : '기록이 바뀌었어요.',
                      'fields': fields,
                    },
                  },
                ),
              ),
            );
          }

          Object? data;
          if (private && expire) {
            fail(401, 'AUTH_REQUIRED');
            return;
          }
          if (path == '/api/v1/foods') {
            data = {
              'items': [food],
              'total': 1,
              'offset': options.queryParameters['offset'] ?? 0,
            };
          } else if (path == '/api/v1/nutrition/calculate') {
            if (stale) {
              fail(
                409,
                'FOOD_REVISION_CHANGED',
                fields: [
                  {
                    'field': 'body.items.0.revision_id',
                    'reason': 'revision_changed',
                  },
                ],
              );
              return;
            }
            final selections = options.data['items'] as List;
            data = {
              'total': _total(selections),
              'items': [
                for (final row in selections)
                  {
                    'food_name': '쌀밥',
                    'status': 'computed',
                    'amount': _amount(row),
                    'note': '',
                  },
              ],
            };
          } else if (path == '/api/v1/meals' && options.method == 'POST') {
            final key = options.headers['Idempotency-Key'] as String;
            final payload = Map<String, dynamic>.from(options.data as Map);
            if (stale) {
              fail(
                409,
                'FOOD_REVISION_CHANGED',
                fields: [
                  {
                    'field': 'body.items.0.revision_id',
                    'reason': 'revision_changed',
                  },
                ],
              );
              return;
            }
            if (!receipts.containsKey(key)) {
              receipts[key] = jsonEncode(payload);
              meal = _record(payload);
            }
            expect(receipts[key], jsonEncode(payload));
            if (loseNextAck) {
              loseNextAck = false;
              handler.reject(
                DioException(
                  requestOptions: options,
                  type: DioExceptionType.receiveTimeout,
                ),
              );
              return;
            }
            data = {'meal': meal, 'replayed': receipts.length == 1};
          } else if (path == '/api/v1/meals') {
            data = {
              'items': meal == null
                  ? []
                  : [
                      {...meal!}..remove('items'),
                    ],
              'total': meal == null ? 0 : 1,
              'offset': 0,
            };
          } else if (private && options.method == 'GET') {
            data = meal;
          } else if (private && options.method == 'PATCH') {
            if (options.data['expected_version'] != meal!['version'] ||
                conflict) {
              fail(409, 'MEAL_VERSION_CHANGED');
              return;
            }
            final old = meal!;
            if (options.data['items'] != null) {
              meal = _record(Map<String, dynamic>.from(options.data as Map));
            }
            meal!['eaten_at'] = options.data['eaten_at'];
            meal!['version'] = (old['version'] as int) + 1;
            data = meal;
          } else if (private && options.method == 'DELETE') {
            final version = Uri.parse(options.path).queryParameters['version'];
            if (version != meal!['version'].toString() || conflict) {
              fail(409, 'MEAL_VERSION_CHANGED');
              return;
            }
            meal = null;
          } else {
            throw StateError('Unexpected request $path');
          }
          afterResponse?.call();
          handler.resolve(
            Response(
              requestOptions: options,
              statusCode: options.method == 'DELETE' ? 204 : 200,
              data: {'data': data},
            ),
          );
        },
      ),
    );
    client = ApiClient(dio: dio);
    account =
        Account(
            AuthApi(client),
            storage,
            profiles: ProfileApi(client),
            serverUrl: origin,
            kakaoEnabled: false,
          )
          ..session = ServiceSession(
            userId: 'owner-1',
            token: List.filled(43, 'a').join(),
            expiresAt: DateTime.now().add(const Duration(days: 3)),
            kakaoLinked: false,
          );
    api = reopen();
  }
  static const origin = 'https://example.test';
  final storage = _Storage();
  late final ApiClient client;
  late final Account account;
  late final IntakeApi api;
  final requests = <RequestOptions>[];
  final receipts = <String, String>{};
  bool loseNextAck = false, stale = false, conflict = false;
  bool expire = false;
  void Function()? afterResponse;
  Map<String, dynamic>? meal;
  IntakeApi reopen({String serverOrigin = origin}) =>
      IntakeApi(client, account, storage, serverOrigin: serverOrigin);
  final food = <String, dynamic>{
    'food_id': '00000000-0000-0000-0000-000000000001',
    'name': '쌀밥',
    'basis': {'text': '100g', 'unit': 'g'},
    'source': {'revision_id': '00000000-0000-0000-0000-000000000002'},
    'category': '밥류',
    'dish_serving_text': '200g',
    'serving_ref_text': null,
  };
  FoodSelection get selection =>
      FoodSelection(FoodChoice.fromJson(food), 100, 'g');
  double _amount(dynamic row) =>
      (row['amount'] as num).toDouble() * (row['unit'] == '인분' ? 200 : 1);
  Map<String, dynamic> _total(List selections) => {
    'complete': true,
    'approx_ml_items': 0,
    'missing_items': {'fat_g': selections.length},
    'nutrients': {
      'energy_kcal': selections.fold<double>(
        0,
        (sum, row) => sum + _amount(row) * 1.5,
      ),
      'protein_g': 3,
      'carbohydrate_g': 30,
      'fat_g': null,
      'sodium_mg': 0,
    },
  };
  Map<String, dynamic> _record(Map<String, dynamic> payload) => {
    'id': 'record-1',
    'version': 1,
    'eaten_at': payload['eaten_at'],
    'legacy_snapshot_missing': false,
    'total': _total(payload['items'] as List),
    'items': [
      for (final row in payload['items'] as List)
        {
          'food_id': food['food_id'],
          'revision_id': (food['source'] as Map)['revision_id'],
          'name': food['name'],
          'amount': _amount(row),
          'amount_unit': 'g',
          'calculation': {
            'basis': food['basis'],
            'input': row,
            'serving': row['unit'] == '인분' ? {'text': '200g'} : null,
          },
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
  TestWidgetsFlutterBinding.ensureInitialized();
  late DemoRepository repository;
  setUpAll(() async => repository = await DemoRepository.load());
  final stamp = DateTime.utc(2026, 11, 19, 23);
  PhotoRecognition photo(_Server server) => PhotoRecognition([
    PhotoDish('쌀밥', 'high', 150, [
      PhotoMatch(FoodChoice.fromJson(server.food), 200, 'g', '원천 1회 분량 참고'),
    ]),
  ], '사진에서 실제 양을 측정한 값이 아닌 예상 1인분이에요.');

  testWidgets(
    'confirmed ingredients keep other dishes, allow quantity edits, and never silently omit missing ingredients',
    (tester) async {
      final server = _Server();
      final ai = _IngredientAi(
        () async => IngredientEstimate(
          [
            IngredientGuess('쌀', 80, [
              PhotoMatch(
                FoodChoice.fromJson(server.food),
                80,
                'g',
                'AI 예상 재료량',
              ),
            ]),
            const IngredientGuess('못찾은양념', 5, []),
          ],
          '일반 조리법으로 예상한 재료예요.',
          referenceName: '검증레시피',
        ),
      );
      await _pump(
        tester,
        PhotoFoodScreen(
          result: PhotoRecognition([
            photo(server).foods.first,
            const PhotoDish('이름모를볶음밥', 'medium', 250, []),
          ], '음식 후보예요.'),
          api: server.api,
          aiApi: ai,
        ),
      );
      await tester.scrollUntilVisible(find.text('AI로 재료 추정하기'), 180);
      await tester.pumpAndSettle();
      expect(ai.calls, 0);
      await tester.tap(find.text('AI로 재료 추정하기'));
      await tester.pumpAndSettle();
      expect(ai.calls, 1);
      expect(ai.requestedName, '이름모를볶음밥');
      expect(ai.requestedGrams, 250);
      expect(find.textContaining('공공 레시피 검증레시피'), findsOneWidget);
      await tester.scrollUntilVisible(
        find.byKey(const Key('ingredients-confirm')),
        180,
      );
      expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('ingredients-confirm')))
            .onPressed,
        isNull,
      );
      expect(server.requests, isEmpty);
      await tester.ensureVisible(find.text('양 바꾸기'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('양 바꾸기'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('food-amount')), '120');
      await tester.ensureVisible(find.text('이 양으로 담기'));
      await tester.tap(find.text('이 양으로 담기'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.widgetWithText(CheckboxListTile, '못찾은양념'),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(CheckboxListTile, '못찾은양념'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('ingredients-confirm')));
      await tester.pumpAndSettle();
      expect(find.text('빠진 재료가 있는 참고값으로 계속'), findsOneWidget);
      await tester.tap(find.byKey(const Key('ingredients-confirm')));
      await tester.pumpAndSettle();
      final half = find.widgetWithText(ChoiceChip, '반 정도').last;
      await tester.ensureVisible(half);
      await tester.pumpAndSettle();
      await tester.tap(half);
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      final request = server.requests.singleWhere(
        (r) => r.path.endsWith('/nutrition/calculate'),
      );
      expect((request.data['items'] as List).map((item) => item['amount']), [
        200,
        60,
      ]);
      expect(
        (request.data['items'] as List).every(
          (item) => item['amount_is_estimate'] == true,
        ),
        isTrue,
      );
      expect(find.textContaining('빠진 기름·양념'), findsOneWidget);
      expect(server.meal, isNull);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'ingredient errors can retry and water or unmatched-only results cannot calculate',
    (tester) async {
      var first = true;
      final server = _Server();
      final ai = _IngredientAi(() async {
        if (first) {
          first = false;
          throw const ApiException(ApiErrorType.network, '연결이 끊겼어요.');
        }
        return const IngredientEstimate([
          IngredientGuess('물', 100, [], isWater: true),
          IngredientGuess('못찾은재료', 10, []),
        ], '예상 재료예요.');
      });
      await _pump(
        tester,
        IngredientReviewScreen(
          aiApi: ai,
          intakeApi: server.api,
          name: '새 요리',
          grams: 200,
        ),
      );
      expect(find.text('연결이 끊겼어요.'), findsOneWidget);
      await tester.tap(find.text('다시 시도'));
      await tester.pumpAndSettle();
      expect(ai.calls, 2);
      expect(find.text('조리용 물은 영양 합산에서 제외해요.'), findsOneWidget);
      await tester.scrollUntilVisible(
        find.byKey(const Key('ingredients-confirm')),
        180,
      );
      expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('ingredients-confirm')))
            .onPressed,
        isNull,
      );
      expect(server.requests, isEmpty);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'similar food shows source nutrients and requires selection before calculation',
    (tester) async {
      final server = _Server();
      final candidate = PhotoMatch.fromJson({
        'match_basis': 'similar',
        'food': {
          ...server.food,
          'nutrients': {
            'energy_kcal': 150,
            'protein_g': 3,
            'carbohydrate_g': 30,
            'fat_g': null,
            'sodium_mg': 0,
          },
        },
        'serving': {'amount': 200, 'unit': 'g', 'description': '예상 1인분'},
      });
      await _pump(
        tester,
        PhotoFoodScreen(
          result: PhotoRecognition([
            PhotoDish('잡곡밥', 'medium', 200, [candidate]),
          ], '음식 후보예요.'),
          api: server.api,
        ),
      );
      expect(candidate.isSimilar, isTrue);
      expect(candidate.nutrients!.values['fat_g'], isNull);
      expect(find.textContaining('이름이 비슷한 음식'), findsOneWidget);
      expect(find.textContaining('열량 150 kcal'), findsOneWidget);
      expect(find.textContaining('지방 정보 없음'), findsOneWidget);
      expect(server.requests, isEmpty);
      await tester.scrollUntilVisible(find.text('이 음식으로 영양 확인'), 180);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, '이 음식으로 영양 확인'),
            )
            .onPressed,
        isNull,
      );
      await tester.ensureVisible(find.textContaining('쌀밥 선택'));
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('쌀밥 선택'));
      await tester.pumpAndSettle();
      expect(find.textContaining('잡곡밥 대신 쌀밥'), findsOneWidget);
      expect(server.requests, isEmpty);
      await tester.ensureVisible(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      final request = server.requests.singleWhere(
        (r) => r.path.endsWith('/nutrition/calculate'),
      );
      expect(request.data['items'][0]['food_id'], server.food['food_id']);
      expect(request.data['items'][0]['amount'], 200);
      expect(request.data['items'][0]['amount_is_estimate'], isTrue);
      expect(server.meal, isNull);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'unmatched photo can search its recognized name without retyping',
    (tester) async {
      final server = _Server();
      await _pump(
        tester,
        PhotoFoodScreen(
          result: const PhotoRecognition([
            PhotoDish('잡곡밥', 'low', 200, []),
          ], '음식 후보예요.'),
          api: server.api,
        ),
      );
      expect(find.textContaining('비슷한 음식도 찾지 못했어요'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('다른 음식 검색'), 180);
      await tester.tap(find.text('다른 음식 검색'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('food-search')))
            .controller!
            .text,
        '잡곡밥',
      );
      expect(server.requests.single.path, contains('/api/v1/foods'));
      expect(server.requests.single.queryParameters['q'], '잡곡밥');
      expect(tester.takeException(), isNull);
    },
  );

  test(
    'legacy photo response without similarity or nutrient fields still decodes',
    () {
      final server = _Server();
      final match = PhotoMatch.fromJson({
        'food': server.food,
        'serving': {'amount': 200, 'unit': 'g', 'description': '원천 1회 분량'},
      });
      expect(match.isSimilar, isFalse);
      expect(match.nutrients, isNull);
    },
  );

  testWidgets(
    'photo starts at one serving, half portion changes calculation without auto-save',
    (tester) async {
      final server = _Server();
      await _pump(
        tester,
        PhotoFoodScreen(result: photo(server), api: server.api),
      );
      expect(
        tester
            .widget<ChoiceChip>(find.widgetWithText(ChoiceChip, '1인분'))
            .selected,
        isTrue,
      );
      await tester.tap(find.text('반 정도'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      final request = server.requests.singleWhere(
        (r) => r.path.endsWith('/nutrition/calculate'),
      );
      expect(request.data['items'][0]['amount'], 100);
      expect(request.data['items'][0]['amount_is_estimate'], isTrue);
      expect(find.text('예상 분량 · 실제 먹은 양과 다를 수 있어요'), findsOneWidget);
      expect(server.requests.where((r) => r.path == '/api/v1/meals'), isEmpty);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'pending meal confirmation preserves photo selection for a later new save',
    (tester) async {
      final server = _Server();
      await server.api.prepare(stamp, [server.selection]);
      await _pump(
        tester,
        PhotoFoodScreen(result: photo(server), api: server.api),
      );
      await tester.ensureVisible(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      expect(find.textContaining('이전 식사의 저장 확인이 먼저예요'), findsOneWidget);
      expect(
        server.requests.where((r) => r.path.endsWith('/nutrition/calculate')),
        isEmpty,
      );
      await tester.scrollUntilVisible(
        find.byKey(const Key('intake-save')).hitTestable(),
        250,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('intake-save')));
      await tester.pumpAndSettle();
      expect(find.byType(PhotoFoodScreen), findsOneWidget);
      await tester.ensureVisible(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('이 음식으로 영양 확인'));
      await tester.pumpAndSettle();
      final request = server.requests.singleWhere(
        (r) => r.path.endsWith('/nutrition/calculate'),
      );
      expect(request.data['items'][0]['amount'], 200);
      expect(tester.takeException(), isNull);
    },
  );

  test(
    'estimated portion survives pending storage and saved snapshot decoding',
    () {
      final server = _Server();
      final item = FoodSelection(
        server.selection.food,
        200,
        'g',
        estimated: true,
      );
      expect(FoodSelection.fromStorage(item.toStorage()).estimated, isTrue);
      final saved = server._record({
        'eaten_at': stamp.toIso8601String(),
        'items': [item.toJson()],
      });
      (saved['items'][0]['calculation'] as Map)['amount_is_estimate'] = true;
      expect(SavedIntake.fromJson(saved).items.single.estimated, isTrue);
      expect(
        server.selection.toJson().containsKey('amount_is_estimate'),
        isFalse,
      );
    },
  );
  test(
    'non-restorable amounts and units are rejected before persistence or transmission',
    () async {
      final server = _Server();
      for (final selection in [
        FoodSelection(server.selection.food, double.nan, 'g'),
        FoodSelection(server.selection.food, 0, 'g'),
        FoodSelection(server.selection.food, 1, 'kg'),
      ]) {
        await expectLater(
          server.api.prepare(stamp, [selection]),
          throwsA(isA<ApiException>()),
        );
      }
      expect(server.storage.values, isEmpty);
      expect(server.requests, isEmpty);
    },
  );
  test(
    'simultaneous save preparation reuses one durable request key',
    () async {
      final server = _Server();
      final attempts = await Future.wait([
        server.api.prepare(stamp, [server.selection]),
        server.api.prepare(stamp, [server.selection]),
      ]);
      expect(attempts[0].key, attempts[1].key);
      expect(server.storage.values.length, 1);
    },
  );
  test(
    'expired identity keeps its pending save and never silently starts a new guest',
    () async {
      final server = _Server();
      final pending = await server.api.prepare(stamp, [server.selection]);
      server.expire = true;
      await expectLater(
        server.api.submit(pending),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 401)),
      );
      expect(server.account.session, isNull);
      await expectLater(server.api.pending(), throwsA(isA<ApiException>()));
      expect(server.requests.length, 1);
      expect(server.storage.values.keys.single, endsWith(':owner-1'));
    },
  );
  test(
    'a lost acknowledgement survives app recreation and replays the same meal once',
    () async {
      final server = _Server()..loseNextAck = true;
      final attempt = await server.api.prepare(stamp, [server.selection]);
      await expectLater(
        server.api.submit(attempt),
        throwsA(isA<ApiException>()),
      );
      expect(server.meal, isNotNull);
      final restored = await server.reopen().pending();
      expect(restored!.key, attempt.key);
      expect(restored.body, attempt.body);
      final saved = await server.reopen().submit(restored);
      expect(saved.total.nutrients.values['energy_kcal'], 150);
      expect(server.receipts.length, 1);
      expect(await server.api.pending(), isNull);
    },
  );
  test(
    'pending saves are isolated by origin and user and never sent as another account',
    () async {
      final server = _Server();
      final pending = await server.api.prepare(stamp, [server.selection]);
      expect(
        await server.reopen(serverOrigin: 'https://other.test').pending(),
        isNull,
      );
      server.account.session = ServiceSession(
        userId: 'owner-2',
        token: List.filled(43, 'b').join(),
        expiresAt: stamp.add(const Duration(days: 5)),
        kakaoLinked: false,
      );
      expect(await server.api.pending(), isNull);
      await expectLater(
        server.api.submit(pending),
        throwsA(isA<ApiException>()),
      );
      expect(server.requests, isEmpty);
    },
  );
  test(
    'local write failure blocks transmission and unknown saved data is not discarded',
    () async {
      final server = _Server();
      server.storage.failWrite = true;
      await expectLater(
        server.api.prepare(stamp, [server.selection]),
        throwsA(isA<ApiException>()),
      );
      expect(server.requests, isEmpty);
      server.storage.values['pending-intake:${_Server.origin}:owner-1'] =
          '{broken';
      await expectLater(server.api.pending(), throwsA(isA<ApiException>()));
      expect(server.storage.values.values.single, '{broken');
      server.storage.values['service-session:${_Server.origin}'] =
          'session-to-preserve';
      await server.api.clearBrokenPendingAfterReview();
      expect(server.storage.values, {
        'service-session:${_Server.origin}': 'session-to-preserve',
      });
    },
  );
  test(
    'definitive source rejection permits correction and reports the item to change',
    () async {
      final server = _Server();
      final pending = await server.api.prepare(stamp, [server.selection]);
      server.stale = true;
      await expectLater(
        server.api.submit(pending),
        throwsA(
          isA<ApiException>().having((e) => e.fields, 'fields', [
            'body.items.0.revision_id',
          ]),
        ),
      );
      expect(await server.api.pending(), isNull);
      expect(server.receipts, isEmpty);
    },
  );
  test(
    'different input cannot overwrite an unresolved create request',
    () async {
      final server = _Server();
      final first = await server.api.prepare(stamp, [server.selection]);
      await expectLater(
        server.api.prepare(stamp.add(const Duration(minutes: 1)), [
          server.selection,
        ]),
        throwsA(isA<ApiException>()),
      );
      expect((await server.api.pending())!.key, first.key);
      expect(server.requests, isEmpty);
    },
  );
  test(
    'history dates are Korean calendar dates and updates carry a version',
    () async {
      final server = _Server();
      expect(
        intakeDate(koreanTime(DateTime.utc(2026, 11, 19, 15))),
        '2026-11-20',
      );
      final saved = await server.api.submit(
        await server.api.prepare(stamp, [server.selection]),
      );
      await server.api.history(DateTime(2026, 11, 20));
      expect(server.requests.last.queryParameters['day'], '2026-11-20');
      final updated = await server.api.update(
        saved,
        stamp.add(const Duration(hours: 1)),
      );
      expect(updated.version, 2);
      expect((server.requests.last.data as Map).containsKey('items'), isFalse);
      server.conflict = true;
      await expectLater(
        server.api.update(saved, stamp),
        throwsA(
          isA<ApiException>().having(
            (e) => e.code,
            'code',
            'MEAL_VERSION_CHANGED',
          ),
        ),
      );
      server.conflict = false;
      await server.api.remove(updated);
      expect(server.meal, isNull);
    },
  );
  test('only a source weight reference enables serving units', () {
    final food = _Server().food;
    expect(
      FoodChoice.fromJson({...food, 'dish_serving_text': null}).hasServing,
      isFalse,
    );
    expect(
      FoodChoice.fromJson({...food, 'dish_serving_text': '0g'}).hasServing,
      isFalse,
    );
    expect(
      FoodChoice.fromJson({
        ...food,
        'dish_serving_text': '1개',
        'serving_ref_text': '250mL',
      }).servingReference,
      '250mL',
    );
  });
  test(
    'acknowledged records remain successful if local receipt cleanup fails',
    () async {
      final server = _Server();
      final pending = await server.api.prepare(stamp, [server.selection]);
      server.storage.failDelete = true;
      final saved = await server.api.submit(pending);
      expect(saved.id, 'record-1');
      expect((await server.api.pending())!.key, pending.key);
      server.storage.failDelete = false;
      expect((await server.api.submit(pending)).id, saved.id);
      expect(server.receipts.length, 1);
    },
  );
  test(
    'account switches during the response do not return the previous user data',
    () async {
      final server = _Server();
      final pending = await server.api.prepare(stamp, [server.selection]);
      server.afterResponse = () => server.account.session = ServiceSession(
        userId: 'owner-2',
        token: List.filled(43, 'b').join(),
        expiresAt: stamp,
        kakaoLinked: false,
      );
      await expectLater(
        server.api.submit(pending),
        throwsA(isA<ApiException>()),
      );
      expect(server.storage.values.keys.single, endsWith(':owner-1'));
    },
  );
  testWidgets(
    'nutrition tab exposes manual records and labels photo examples separately',
    (tester) async {
      final server = _Server();
      server.account.entered = true;
      await _pump(
        tester,
        ValueFlowApp(
          repository: repository,
          settings: AppSettings(textScale: 1.4),
          account: server.account,
          intakeApi: server.api,
        ),
      );
      await tester.tap(find.text('영양분석'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('intake-start')), findsOneWidget);
      expect(find.text('사진 기능 체험'), findsOneWidget);
      await tester.tap(find.byKey(const Key('intake-start')));
      await tester.pumpAndSettle();
      expect(find.text('식사 기록하기'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'large-text flow searches, confirms quantity, previews and saves real intake',
    (tester) async {
      final server = _Server();
      SavedIntake? result;
      await _pump(
        tester,
        Builder(
          builder: (context) => Scaffold(
            body: FilledButton(
              onPressed: () async {
                result = await Navigator.of(context).push<SavedIntake>(
                  MaterialPageRoute(
                    builder: (_) => IntakeEditor(api: server.api),
                  ),
                );
              },
              child: const Text('기록 시작'),
            ),
          ),
        ),
      );
      await tester.tap(find.text('기록 시작'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('intake-add-food')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('food-search')), '쌀밥');
      await tester.tap(find.text('음식 찾기'));
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(Key('food-result-${server.food['food_id']}')),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('원천 1회 분량: 200g'), findsOneWidget);
      await tester.ensureVisible(find.text('이 양으로 담기'));
      await tester.tap(find.text('이 양으로 담기'));
      await tester.pumpAndSettle();
      final preview = find.byKey(const Key('intake-preview'));
      await tester.ensureVisible(preview);
      await tester.tap(preview);
      await tester.pumpAndSettle();
      expect(find.text('300 kcal'), findsOneWidget);
      final save = find.byKey(const Key('intake-save')).hitTestable();
      await tester.scrollUntilVisible(save, 250);
      await tester.tap(save);
      await tester.tap(save);
      await tester.pumpAndSettle();
      expect(result?.items.single.amount, 1);
      expect(result?.items.single.unit, '인분');
      expect((server.meal!['items'] as List).single['amount'], 200);
      expect(server.receipts.length, 1);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'restored pending input is frozen and retries instead of creating a second meal',
    (tester) async {
      final server = _Server()..loseNextAck = true;
      await tester.runAsync(() async {
        final pending = await server.api.prepare(stamp, [server.selection]);
        await expectLater(
          server.api.submit(pending),
          throwsA(isA<ApiException>()),
        );
      });
      SavedIntake? result;
      await _pump(
        tester,
        Builder(
          builder: (context) => Scaffold(
            body: FilledButton(
              onPressed: () async {
                result = await Navigator.of(context).push<SavedIntake>(
                  MaterialPageRoute(
                    builder: (_) => IntakeEditor(api: server.reopen()),
                  ),
                );
              },
              child: const Text('복구 기록 열기'),
            ),
          ),
        ),
      );
      await tester.tap(find.text('복구 기록 열기'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<OutlinedButton>(find.byKey(const Key('intake-add-food')))
            .onPressed,
        isNull,
      );
      await tester.scrollUntilVisible(
        find.byKey(const Key('intake-save')).hitTestable(),
        250,
      );
      expect(find.text('저장 다시 확인'), findsOneWidget);
      await tester.tap(find.byKey(const Key('intake-save')));
      await tester.pumpAndSettle();
      expect(result?.id, 'record-1');
      expect(server.receipts.length, 1);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'large-text detail edits quantities, handles conflict, and confirms deletion',
    (tester) async {
      final server = _Server();
      late SavedIntake saved;
      await tester.runAsync(() async {
        saved = await server.api.submit(
          await server.api.prepare(stamp, [server.selection]),
        );
      });
      await _pump(
        tester,
        Builder(
          builder: (context) => Scaffold(
            body: FilledButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) =>
                      IntakeDetailScreen(api: server.api, id: saved.id),
                ),
              ),
              child: const Text('기록 보기'),
            ),
          ),
        ),
      );
      await tester.tap(find.text('기록 보기'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('음식·양·시간 수정'), 250);
      await tester.tap(find.text('음식·양·시간 수정'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('양 바꾸기'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('food-amount')), '150');
      await tester.tap(find.text('이 양으로 담기'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const Key('intake-preview')),
        250,
      );
      await tester.tap(find.byKey(const Key('intake-preview')));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const Key('intake-save')).hitTestable(),
        250,
      );
      await tester.tap(find.byKey(const Key('intake-save')));
      await tester.pumpAndSettle();
      expect(server.meal!['version'], 2);
      expect((server.meal!['items'] as List).single['amount'], 150);
      server.conflict = true;
      await tester.scrollUntilVisible(
        find.text('이 식사 기록 지우기').hitTestable(),
        250,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('이 식사 기록 지우기').hitTestable());
      await tester.pumpAndSettle();
      await tester.tap(find.text('기록 지우기'));
      await tester.pumpAndSettle();
      expect(server.meal, isNotNull);
      expect(find.text('기록이 바뀌었어요.'), findsOneWidget);
      server.conflict = false;
      await tester.scrollUntilVisible(
        find.text('이 식사 기록 지우기').hitTestable(),
        250,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('이 식사 기록 지우기').hitTestable());
      await tester.pumpAndSettle();
      await tester.tap(find.text('기록 지우기'));
      await tester.pumpAndSettle();
      expect(server.meal, isNull);
      expect(find.text('기록 보기'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
