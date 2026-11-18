import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/guest_session.dart';
import 'package:valueflow/data/meal_recommendation_api.dart';
import 'package:valueflow/data/recipe_api.dart';
import 'package:valueflow/data/recipe_library_api.dart';
import 'package:valueflow/models/recommendations.dart';
import 'package:valueflow/screens/recipe_library_screens.dart';
import 'package:valueflow/screens/server_recipe_screens.dart';
import 'package:valueflow/services/settings.dart';

class _Server {
  _Server() {
    final examples = jsonDecode(
      File('../../docs/설계/api_examples.json').readAsStringSync(),
    );
    recipe = Map<String, dynamic>.from(
      examples['responses']['recipe_detail']['data'],
    );
    recipe['recipe_id'] = '1';
    recipe['name'] = '쌀죽';
    recipe['images'] = {'small': null, 'large': null};
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          requests.add(options);
          Object? data;
          var status = 200;
          if (options.path.endsWith('/auth/guest')) {
            guests++;
            data = {'access_token': token};
          } else {
            expect(
              options.headers['Authorization'],
              options.path.contains('/recipes') ? anything : 'Bearer $token',
            );
            if (options.headers.containsKey('Authorization')) {
              expect(options.followRedirects, isFalse);
            }
            if (failNext) {
              failNext = false;
              handler.reject(
                DioException(
                  requestOptions: options,
                  type: DioExceptionType.badResponse,
                  response: Response(
                    requestOptions: options,
                    statusCode: 503,
                    data: {
                      'error': {'message': '잠시 후 다시 시도해 주세요.'},
                    },
                  ),
                ),
              );
              return;
            }
            if (options.path == '/api/v1/recipes') {
              data = {
                'items': [recipe],
                'total': 1,
                'limit': 20,
                'offset': 0,
              };
            } else if (options.path == '/api/v1/recipes/1') {
              data = recipe;
            } else if (options.path == '/api/v1/meal/recommendations') {
              data = {'items': [], 'warnings': []};
            } else if (options.path == '/api/v1/saved-recipes') {
              data = {
                'items': saved
                    ? [
                        {'recipe_id': '1', 'name': '쌀죽'},
                      ]
                    : [],
                'total': saved ? 1 : 0,
              };
            } else if (options.path == '/api/v1/saved-recipes/1') {
              if (options.method == 'PUT') saved = true;
              if (options.method == 'DELETE') saved = false;
              data = {'saved': saved};
            } else if (options.path.contains('/meal-plans/')) {
              final parts = options.path.split('/');
              if (options.method == 'PUT') {
                meals[parts.last] = {
                  'meal_slot': parts.last,
                  'recipe_id': options.data['recipe_id'],
                  'recipe_revision_id':
                      options.data['recipe_revision_id'] ?? 'revision',
                  'name': '쌀죽',
                  'is_active': true,
                };
              } else if (options.method == 'DELETE') {
                meals.remove(parts.last);
                status = 204;
              }
              data = {'items': meals.values.toList()};
            } else {
              throw StateError('Unexpected request ${options.path}');
            }
          }
          handler.resolve(
            Response(
              requestOptions: options,
              statusCode: status,
              data: {'data': data},
            ),
          );
        },
      ),
    );
    client = ApiClient(dio: dio);
    session = GuestSession(client);
    library = RecipeLibraryApi(client, session);
    recipes = RecipeApi(client);
  }

  final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
  final token = List.filled(43, 'a').join();
  final requests = <RequestOptions>[];
  final meals = <String, Map<String, dynamic>>{};
  late final Map<String, dynamic> recipe;
  late final ApiClient client;
  late final GuestSession session;
  late final RecipeLibraryApi library;
  late final RecipeApi recipes;
  bool saved = false, failNext = false;
  int guests = 0;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'recommendations, plans and bookmarks share one identity and preserve revision',
    () async {
      final server = _Server();
      final date = DateTime(2026, 11, 18);
      await Future.wait([
        server.library.plan(date),
        server.library.isSaved('1'),
        MealRecommendationApi(server.client, session: server.session).recommend(
          const UserProfile(
            name: '',
            age: 70,
            gender: '선택 안 함',
            region: '',
            district: '',
          ),
          MealTime.lunch,
        ),
      ]);
      expect(server.guests, 1);
      await server.library.putMeal(
        date,
        MealSlot.lunch,
        const RecipeChoice('1', '쌀죽', revisionId: 'saved-revision'),
      );
      final meal = (await server.library.plan(date))[MealSlot.lunch]!;
      expect(meal.recipe.revisionId, 'saved-revision');
      await server.library.setSaved('1', true);
      final reopened = RecipeLibraryApi(server.client, server.session);
      expect((await reopened.saved()).items.single.name, '쌀죽');
      await reopened.setSaved('1', false);
      expect(await reopened.isSaved('1'), isFalse);
      await reopened.removeMeal(date, MealSlot.lunch);
      expect(await reopened.plan(date), isEmpty);
      expect(server.guests, 1);
    },
  );

  test(
    'server failures leave saved state unchanged and can be retried',
    () async {
      final server = _Server();
      await server.library.isSaved('1');
      server.failNext = true;
      await expectLater(
        server.library.setSaved('1', true),
        throwsA(isA<ApiException>()),
      );
      expect(server.saved, isFalse);
      await server.library.setSaved('1', true);
      expect(server.saved, isTrue);
      expect(server.guests, 1);
    },
  );

  Future<void> pump(WidgetTester tester, Widget home) async {
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

  testWidgets('large-text day plan selects, replaces and removes a meal', (
    tester,
  ) async {
    final server = _Server();
    await pump(
      tester,
      MealPlanScreen(
        library: server.library,
        recipes: server.recipes,
        settings: AppSettings(mealPreferences: ['avoid:달걀']),
      ),
    );
    expect(find.text('아직 담은 메뉴가 없어요.'), findsWidgets);
    await tester.tap(find.text('메뉴 고르기').first);
    await tester.pumpAndSettle();
    expect(
      server.requests.last.queryParameters['exclude_allergens'].toString(),
      contains('알류'),
    );
    await tester.tap(find.text('쌀죽'));
    await tester.pumpAndSettle();
    expect(find.text('쌀죽'), findsOneWidget);
    expect(find.text('메뉴 바꾸기'), findsOneWidget);
    await tester.tap(find.text('메뉴 바꾸기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('쌀죽'));
    await tester.pumpAndSettle();
    expect(server.meals.length, 1);
    await tester.tap(find.text('식단에서 빼기'));
    await tester.pumpAndSettle();
    expect(find.text('쌀죽'), findsNothing);
    expect(server.meals, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('recipe save toggles and appears in saved list', (tester) async {
    final server = _Server();
    await pump(
      tester,
      ServerRecipeDetail(
        api: server.recipes,
        recipeId: '1',
        settings: AppSettings(),
        library: server.library,
      ),
    );
    await tester.tap(find.text('레시피 저장'));
    await tester.pumpAndSettle();
    expect(find.text('저장 해제'), findsOneWidget);
    expect(server.saved, isTrue);
    await pump(
      tester,
      SavedRecipesScreen(
        library: server.library,
        recipes: server.recipes,
        settings: AppSettings(),
      ),
    );
    expect(find.text('쌀죽'), findsOneWidget);
    await tester.tap(find.text('쌀죽'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장 해제'));
    await tester.pumpAndSettle();
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.textContaining('저장한 레시피가 없어요.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'recipe detail asks before replacing an existing meal at large text',
    (tester) async {
      final server = _Server();
      server.meals['breakfast'] = {
        'meal_slot': 'breakfast',
        'recipe_id': '2',
        'recipe_revision_id': 'old-revision',
        'name': '기존 메뉴',
        'is_active': true,
      };
      await pump(
        tester,
        ServerRecipeDetail(
          api: server.recipes,
          recipeId: '1',
          settings: AppSettings(),
          library: server.library,
        ),
      );
      await tester.tap(find.text('식단표에 담기'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('아침'));
      await tester.pumpAndSettle();
      expect(find.text('아침 메뉴를 바꿀까요?'), findsOneWidget);
      expect(server.meals['breakfast']!['recipe_id'], '2');
      await tester.tap(find.text('메뉴 바꾸기'));
      await tester.pumpAndSettle();
      expect(server.meals['breakfast']!['recipe_id'], '1');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('failed plan read offers retry instead of an empty plan', (
    tester,
  ) async {
    final server = _Server()..failNext = true;
    await pump(
      tester,
      MealPlanScreen(
        library: server.library,
        recipes: server.recipes,
        settings: AppSettings(),
      ),
    );
    expect(find.text('메뉴 고르기'), findsNothing);
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(find.text('메뉴 고르기'), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
