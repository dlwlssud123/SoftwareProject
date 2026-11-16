import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/data/meal_recommendation_api.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/models/recommendations.dart';
import 'package:valueflow/screens/profile_form.dart';
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
                          'steps': [
                            {'no': 1, 'text': '끓인다'},
                          ],
                          'nutrition': {'protein_g': 3},
                          'allergens': {'detected': []},
                          'images': {'small': null},
                        },
                        'reasons': ['이달의 식재료가 들어 있어요.'],
                        'seasonal_ingredients': [
                          {
                            'name': '쌀',
                            'shopping_search_url':
                                'https://www.coupang.com/np/search?q=rice',
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
      expect(item.seasonal.single.shoppingUrl!.host, 'www.coupang.com');
      expect(result.warnings.single, '공개 표기량을 확인해 주세요.');
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
    await tester.tap(find.byKey(const Key('recommend-submit')));
    await tester.pumpAndSettle();
    expect(find.text('추천 점심 레시피'), findsOneWidget);
    expect(find.text('0세'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
