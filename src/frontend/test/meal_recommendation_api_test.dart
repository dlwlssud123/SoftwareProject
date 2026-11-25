import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/data/meal_recommendation_api.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/models/recommendations.dart';
import 'package:valueflow/screens/profile_form.dart';
import 'package:valueflow/screens/recommendation_results.dart';
import 'package:valueflow/services/settings.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'guest session is reused and only recommendation conditions are sent',
    () async {
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      final token = List.filled(43, 'a').join();
      var guests = 0;
      var recommendations = 0;
      var includeSeasonalEvidence = true;
      var seasonalMonth = 11;
      var seasonalSource = 'https://www.nics.go.kr/food';
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            if (options.path == '/api/v1/auth/guest') {
              guests++;
              expect(options.followRedirects, isFalse);
              handler.resolve(
                Response(
                  requestOptions: options,
                  data: {
                    'data': {'access_token': token},
                  },
                ),
              );
              return;
            }
            recommendations++;
            expect(options.path, '/api/v1/meal/recommendations');
            expect(options.headers['Authorization'], 'Bearer $token');
            expect(options.followRedirects, isFalse);
            expect(options.data, {
              'meal_time': 'lunch',
              'soft_food': true,
              'simple_cooking': true,
              'preferred_ingredients': ['두부'],
              'health_conditions': ['hypertension'],
              'exclude_allergens': ['알류'],
            });
            handler.resolve(
              Response(
                requestOptions: options,
                data: {
                  'data': {
                    'items': [
                      {
                        'item': {
                          'recipe_id': '1',
                          'name': '쌀죽',
                          'ingredients_text': '쌀 100g',
                          'ingredients': [
                            {'name': '쌀'},
                          ],
                          'steps': [
                            {'no': 1, 'text': '끓인다'},
                          ],
                          'nutrition': {'protein_g': 3},
                          'allergens': {'detected': []},
                          'images': {'small': null},
                        },
                        'reasons': ['이달의 식재료가 들어 있어요.'],
                        'matched_preferences': ['soft_food', 'simple_cooking'],
                        'seasonal_ingredients': [
                          {
                            'name': '쌀',
                            'shopping_search_url':
                                'https://www.coupang.com/np/search?q=쌀',
                            if (includeSeasonalEvidence) ...{
                              'seasonal_food_id':
                                  '00000000-0000-4000-8000-000000000001',
                              'month': seasonalMonth,
                              'source_url': seasonalSource,
                            },
                          },
                        ],
                      },
                    ],
                    'warnings': ['공개 표기량을 확인해 주세요.'],
                  },
                },
              ),
            );
          },
        ),
      );
      FlutterSecureStorage.setMockInitialValues({});
      final client = ApiClient(dio: dio);
      const storageKey = 'mealGuest:https://example.test';
      final api = MealRecommendationApi(client, guestStorageKey: storageKey);
      const profile = UserProfile(
        name: '예시 이름',
        age: 72,
        gender: '선택 안 함',
        region: '서울특별시',
        district: '노원구',
        conditions: {'고혈압'},
        allergies: {'달걀'},
        softFood: true,
        simpleCooking: true,
        preferredIngredients: {'두부'},
      );
      final result = await api.recommend(profile, MealTime.lunch);
      await MealRecommendationApi(
        client,
        guestStorageKey: storageKey,
      ).recommend(profile, MealTime.lunch);
      expect(guests, 1);
      expect(recommendations, 2);
      final item = result.items.single;
      expect(item.recipe.calories, isNull);
      expect(item.recipe.protein, 3);
      expect(item.recipe.steps, ['1. 끓인다']);
      expect(item.softMatch, isTrue);
      expect(item.simpleMatch, isTrue);
      expect(item.ingredientCount, 1);
      expect(item.seasonal.single.shoppingUrl!.host, 'www.coupang.com');
      expect(item.seasonal.single.month, 11);
      expect(item.seasonal.single.sourceUrl!.host, 'www.nics.go.kr');
      expect(result.warnings.single, '공개 표기량을 확인해 주세요.');
      includeSeasonalEvidence = false;
      final older = await api.recommend(profile, MealTime.lunch);
      expect(older.items.single.seasonal.single.month, isNull);
      expect(older.items.single.seasonal.single.sourceUrl, isNull);
      includeSeasonalEvidence = true;
      seasonalMonth = 13;
      seasonalSource = 'https://www.nics.go.kr.evil.test/food';
      final invalidEvidence = await api.recommend(profile, MealTime.lunch);
      expect(invalidEvidence.items.single.seasonal.single.month, isNull);
      expect(invalidEvidence.items.single.seasonal.single.sourceUrl, isNull);
    },
  );

  testWidgets('connected meal can start without demographics at large text', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final guest = options.path.endsWith('/guest');
          if (!guest) expect(options.data['exclude_allergens'], ['알류']);
          handler.resolve(
            Response(
              requestOptions: options,
              data: {
                'data': guest
                    ? {'access_token': List.filled(43, 'a').join()}
                    : {'items': [], 'warnings': []},
              },
            ),
          );
        },
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: const TextScaler.linear(1.4)),
          child: child!,
        ),
        home: ProfileForm(
          repository: const DemoRepository([], []),
          settings: AppSettings(mealPreferences: ['avoid:달걀']),
          mealApi: MealRecommendationApi(ApiClient(dio: dio)),
        ),
      ),
    );
    expect(find.byType(TextFormField), findsNothing);
    expect(find.byKey(const Key('profile-next')), findsNothing);
    final allergyButton = find.byKey(const Key('meal-allergy-settings'));
    expect(allergyButton.hitTestable(), findsOneWidget);
    expect(find.text('달걀 제외'), findsOneWidget);
    await tester.tap(allergyButton);
    await tester.pumpAndSettle();
    expect(find.text('알레르기 설정'), findsOneWidget);
    await tester.tap(find.text('우유'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(find.text('달걀 제외'), findsOneWidget);
    await tester.tap(find.byKey(const Key('recommend-submit')));
    await tester.pumpAndSettle();
    expect(find.text('추천 점심 레시피'), findsOneWidget);
    expect(find.text('0세'), findsNothing);
    expect(find.textContaining('제품 표시를 확인'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'results show warnings first and group matching cooking options',
    (tester) async {
      const recipe = Recipe(
        id: '1',
        name: '두부찜',
        ingredients: '두부 100g',
        steps: ['1. 찐다'],
        calories: null,
        sodium: null,
        protein: null,
        carbs: null,
        fat: null,
        method: '찌기',
        allergens: {},
        soft: false,
        fromServer: true,
      );
      const chosenMatch = RecipeMatch(
        recipe,
        ['재료 1가지, 조리 1단계예요.'],
        simpleMatch: true,
        softMatch: true,
        ingredientCount: 1,
      );
      const otherMatch = RecipeMatch(
        recipe,
        ['다른 추천 이유'],
        simpleMatch: false,
        softMatch: false,
        ingredientCount: 1,
      );
      await tester.pumpWidget(
        MaterialApp(
          home: RecommendationResults(
            repository: const DemoRepository([], []),
            settings: AppSettings(),
            time: MealTime.lunch,
            profile: const UserProfile(
              name: '',
              age: 0,
              gender: '',
              region: '',
              district: '',
              conditions: {'고혈압'},
              simpleCooking: true,
              softFood: true,
            ),
            serverMeals: const MealRecommendations(
              [otherMatch, chosenMatch],
              ['기준 분량 확인 필요'],
            ),
          ),
        ),
      );
      final warning = find.text('기준 분량 확인 필요');
      final preferred = find.text('조리 조건을 반영한 메뉴');
      expect(
        tester.getTopLeft(warning).dy,
        lessThan(tester.getTopLeft(preferred).dy),
      );
      expect(find.text('나트륨 표기량 참고'), findsOneWidget);
      expect(find.text('부드러운 조리'), findsOneWidget);
      final other = find.text('다른 추천 메뉴');
      await tester.scrollUntilVisible(other, 250);
      expect(other.hitTestable(), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
