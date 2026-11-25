import 'dart:io';
import 'dart:ui' as ui;
import 'package:dio/io.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/ai_api.dart';
import 'package:valueflow/data/auth_api.dart';
import 'package:valueflow/data/intake_api.dart';
import 'package:valueflow/data/profile_api.dart';
import 'package:valueflow/models/ai.dart';
import 'package:valueflow/models/intake.dart';
import 'package:valueflow/screens/intake_screens.dart';
import 'package:valueflow/screens/photo_food_screen.dart';
import 'package:valueflow/services/account.dart';
import 'package:valueflow/theme.dart';

// Only local persistence is in memory. Dio, the API, migrations and PostgreSQL are real.
class _Storage implements FlutterSecureStorage {
  final values = <String, String>{};
  @override
  dynamic noSuchMethod(Invocation invocation) {
    final key = invocation.namedArguments[#key] as String;
    if (invocation.memberName == #read) {
      return Future<String?>.value(values[key]);
    }
    if (invocation.memberName == #write) {
      values[key] = invocation.namedArguments[#value] as String;
      return Future<void>.value();
    }
    if (invocation.memberName == #delete) {
      values.remove(key);
      return Future<void>.value();
    }
    return super.noSuchMethod(invocation);
  }
}

void main() => runNutritionIntegration();

class _DirectHttp extends HttpOverrides {}

Dio networkDio(BaseOptions options) => Dio(options)
  ..httpClientAdapter = IOHttpClientAdapter(
    createHttpClient: () => _DirectHttp().createHttpClient(null),
  );

Future<void> capture(
  WidgetTester tester,
  bool native,
  TestWidgetsFlutterBinding binding,
  String name,
) async {
  await tester.pump();
  if (native) {
    await (binding as IntegrationTestWidgetsFlutterBinding).takeScreenshot(
      name,
    );
    return;
  }
  const output = String.fromEnvironment('NUTRITION_QA_SCREENSHOT_DIR');
  if (output.isEmpty) return;
  final boundary = tester.renderObject<RenderRepaintBoundary>(
    find.byType(RepaintBoundary).first,
  );
  final image = await boundary.toImage();
  final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
  image.dispose();
  await Directory(output).create(recursive: true);
  await File('$output/$name.png').writeAsBytes(bytes!.buffer.asUint8List());
}

void runNutritionIntegration({bool native = false}) {
  final binding = native
      ? IntegrationTestWidgetsFlutterBinding.ensureInitialized()
      : TestWidgetsFlutterBinding.ensureInitialized();
  const base = String.fromEnvironment('NUTRITION_QA_BASE_URL');
  const liveAi = bool.fromEnvironment('NUTRITION_QA_LIVE_AI');

  setUpAll(() async {
    const font = String.fromEnvironment('NUTRITION_QA_FONT_FILE');
    if (!native && font.isNotEmpty) {
      final bytes = await File(font).readAsBytes();
      await (FontLoader(
        'QAKorean',
      )..addFont(Future.value(ByteData.sublistView(bytes)))).load();
    }
  });

  ThemeData testTheme() => appTheme().copyWith(
    textTheme: appTheme().textTheme.apply(
      fontFamily: const String.fromEnvironment('NUTRITION_QA_FONT_FILE').isEmpty
          ? null
          : 'QAKorean',
    ),
  );

  void verifyLocalTarget() {
    final uri = Uri.parse(base);
    expect({'127.0.0.1', '10.0.2.2', 'localhost'}, contains(uri.host));
    expect(uri.port, 18082);
    expect(uri.scheme, 'http');
  }

  Future<void> settle(WidgetTester tester) async {
    final deadline = DateTime.now().add(const Duration(seconds: 45));
    do {
      await tester.pump(const Duration(milliseconds: 100));
      await Future<void>.delayed(const Duration(milliseconds: 20));
      if (!binding.hasScheduledFrame) return;
    } while (DateTime.now().isBefore(deadline));
    throw TestFailure('The screen did not settle within 45 seconds');
  }

  Future<void> waitFor(WidgetTester tester, Finder finder) async {
    final deadline = DateTime.now().add(const Duration(seconds: 45));
    while (finder.evaluate().isEmpty && DateTime.now().isBefore(deadline)) {
      await tester.pump(const Duration(milliseconds: 100));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    expect(finder, findsOneWidget);
  }

  Future<void> tap(WidgetTester tester, Finder finder) async {
    if (finder.evaluate().isEmpty) {
      await tester.scrollUntilVisible(finder, 160);
    }
    await tester.ensureVisible(finder);
    await settle(tester);
    await tester.tap(finder);
    await settle(tester);
    expect(tester.takeException(), isNull);
  }

  Account account(ApiClient client, _Storage storage) => Account(
    AuthApi(client),
    storage,
    profiles: ProfileApi(client),
    serverUrl: base,
    kakaoEnabled: false,
  );

  testWidgets(
    'real API photo choice saves once after lost response and preserves evidence',
    (tester) async {
      await tester.runAsync(() async {
        verifyLocalTarget();
        if (!native) {
          tester.view.physicalSize = const Size(320, 720);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
        }
        final dio = networkDio(
          BaseOptions(
            baseUrl: base,
            connectTimeout: const Duration(seconds: 10),
            receiveTimeout: const Duration(seconds: 40),
          ),
        );
        addTearDown(() => dio.close(force: true));
        final client = ApiClient(dio: dio), storage = _Storage();
        final owner = account(client, storage);
        await owner.startGuest();
        expect(owner.session, isNotNull);
        addTearDown(() => AuthApi(client).revoke(owner.session!.token));
        final api = IntakeApi(client, owner, storage, serverOrigin: base);
        final rice = (await api.foods('쌀밥')).items.single;
        final photo = PhotoRecognition([
          PhotoDish('사진 속 밥', 'medium', 200, [
            PhotoMatch(
              rice,
              200,
              'g',
              'DB 기준량 참고',
              isSimilar: true,
              quantityBasis: 'source_serving',
            ),
          ]),
        ], '합성 인식 후보로 앱과 실제 저장 API 연결을 확인해요.');
        var loseResponse = true;
        dio.interceptors.add(
          InterceptorsWrapper(
            onResponse: (response, handler) {
              if (loseResponse &&
                  response.requestOptions.method == 'POST' &&
                  response.requestOptions.path == '/api/v1/meals') {
                loseResponse = false;
                handler.reject(
                  DioException(
                    requestOptions: response.requestOptions,
                    type: DioExceptionType.connectionError,
                    message:
                        'Injected lost acknowledgement after the server committed',
                  ),
                );
              } else {
                handler.next(response);
              }
            },
          ),
        );
        SavedIntake? saved;
        await tester.pumpWidget(
          MaterialApp(
            theme: testTheme(),
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(
                context,
              ).copyWith(textScaler: const TextScaler.linear(1.4)),
              child: child!,
            ),
            home: Builder(
              builder: (context) => Scaffold(
                body: FilledButton(
                  onPressed: () async {
                    saved = await Navigator.of(context).push<SavedIntake>(
                      MaterialPageRoute(
                        builder: (_) =>
                            PhotoFoodScreen(result: photo, api: api),
                      ),
                    );
                  },
                  child: const Text('통합 검증 시작'),
                ),
              ),
            ),
          ),
        );
        await settle(tester);
        if (native) {
          await (binding as IntegrationTestWidgetsFlutterBinding)
              .convertFlutterSurfaceToImage();
        }
        await tap(tester, find.text('통합 검증 시작'));
        await tester.scrollUntilVisible(find.text('이 음식으로 영양 확인'), 180);
        expect(
          tester
              .widget<FilledButton>(
                find.widgetWithText(FilledButton, '이 음식으로 영양 확인'),
              )
              .onPressed,
          isNull,
        );
        await tap(tester, find.textContaining('쌀밥 선택'));
        await tap(tester, find.text('반 정도'));
        await capture(tester, native, binding, 'nutrition-qa-similar-half');
        await tap(tester, find.text('이 음식으로 영양 확인'));
        await waitFor(tester, find.text('확인한 영양 정보'));
        await tester.scrollUntilVisible(find.text('150 kcal'), 150);
        expect(find.text('150 kcal'), findsOneWidget);
        await tap(tester, find.byKey(const Key('intake-save')));
        await waitFor(tester, find.text('저장 다시 확인'));
        expect(saved, isNull);
        expect((await api.history(DateTime.now())).total, 1);
        expect(find.text('저장 다시 확인'), findsOneWidget);
        await capture(tester, native, binding, 'nutrition-qa-retry');
        await tap(tester, find.byKey(const Key('intake-save')));
        await waitFor(tester, find.text('통합 검증 시작'));
        expect(saved, isNotNull);
        expect((await api.history(DateTime.now())).total, 1);
        final detail = await api.detail(saved!.id);
        expect(detail.items.single.amount, 100);
        expect(detail.items.single.estimated, isTrue);
        expect(detail.items.single.origin!.method, 'similar_food');
        expect(detail.items.single.origin!.quantityBasis, 'user_adjusted');
        expect(detail.total.nutrients.values['energy_kcal'], 150);
        expect(detail.analysisContext!.excluded, isEmpty);
        await tester.pumpWidget(
          MaterialApp(
            theme: testTheme(),
            home: IntakeDetailScreen(api: api, id: detail.id),
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(
                context,
              ).copyWith(textScaler: const TextScaler.linear(1.4)),
              child: child!,
            ),
          ),
        );
        await settle(tester);
        await tap(tester, find.text('계산 기준과 제외한 재료'));
        await capture(tester, native, binding, 'nutrition-qa-saved-evidence');
        expect(find.text('입력 방법: 비슷한 음식으로 대체'), findsOneWidget);
        expect(tester.takeException(), isNull);

        final selected = detail.items.single;
        final contextInfo = AnalysisContext([
          const ExcludedIngredient('검증 음식', '소금', 'user_excluded'),
        ]);
        final edited = await api.update(
          detail,
          detail.eatenAt,
          items: [
            FoodSelection(
              selected.food,
              50,
              'g',
              estimated: true,
              origin: selected.origin!.adjusted(),
            ),
          ],
          analysisContext: contextInfo,
        );
        expect(edited.version, detail.version + 1);
        expect(edited.total.nutrients.values['energy_kcal'], 75);
        expect(edited.analysisContext!.excluded.single.name, '소금');
        final other = account(client, _Storage());
        await other.startGuest();
        final otherApi = IntakeApi(
          client,
          other,
          _Storage(),
          serverOrigin: base,
        );
        await expectLater(
          otherApi.detail(edited.id),
          throwsA(
            isA<ApiException>().having((e) => e.statusCode, 'wrong owner', 404),
          ),
        );
        await AuthApi(client).revoke(other.session!.token);
        await api.remove(edited);
        expect((await api.history(DateTime.now())).total, 0);
        debugPrint(
          'REAL_API_NUTRITION: HTTP save/replay/history/edit/owner isolation/delete passed; no backend mock',
        );
      });
    },
    skip: base.isEmpty,
  );

  testWidgets(
    'real NVIDIA photo and ingredient responses decode through the app client',
    (tester) async {
      await tester.runAsync(() async {
        verifyLocalTarget();
        if (!native) {
          tester.view.physicalSize = const Size(320, 720);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
        }
        final dio = networkDio(
          BaseOptions(
            baseUrl: base,
            connectTimeout: const Duration(seconds: 10),
            receiveTimeout: const Duration(seconds: 40),
          ),
        );
        addTearDown(() => dio.close(force: true));
        final client = ApiClient(dio: dio), storage = _Storage();
        final owner = account(client, storage);
        await owner.startGuest();
        addTearDown(() => AuthApi(client).revoke(owner.session!.token));
        final ai = AiApi(client, owner);
        final imageClient = networkDio(
          BaseOptions(
            connectTimeout: const Duration(seconds: 10),
            receiveTimeout: const Duration(seconds: 20),
          ),
        );
        addTearDown(() => imageClient.close(force: true));
        final image = await imageClient.get<List<int>>(
          'https://www.foodsafetykorea.go.kr/uploadimg/20141117/20141117053736_1416213456837.jpg',
          options: Options(responseType: ResponseType.bytes),
        );
        late final PhotoRecognition recognition;
        try {
          recognition = await ai.photo(
            Uint8List.fromList(image.data!),
            CancelToken(),
          );
        } on ApiException catch (error) {
          debugPrint(
            'LIVE_NVIDIA_PHOTO_ERROR: ${error.code}, status=${error.statusCode}, retryable=${error.canRetry}',
          );
          rethrow;
        }
        expect(recognition.foods, isNotEmpty);
        expect(
          recognition.foods.every(
            (food) => food.name.isNotEmpty && food.grams > 0,
          ),
          isTrue,
        );
        final ingredients = await ai.ingredients('양파볶음밥', 250, CancelToken());
        expect(ingredients.ingredients, isNotEmpty);
        expect(ingredients.ingredients.every((item) => item.grams > 0), isTrue);
        expect(
          ingredients.ingredients.any((item) => item.matches.isNotEmpty),
          isTrue,
        );
        debugPrint(
          'REAL_NVIDIA_NUTRITION: public food image and standard-serving ingredients decoded; no provider mock',
        );
      });
    },
    skip: base.isEmpty || !liveAi,
  );
}
