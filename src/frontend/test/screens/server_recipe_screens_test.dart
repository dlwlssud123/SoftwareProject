import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/data/recipe_api.dart';
import 'package:valueflow/models/recipe_record.dart';
import 'package:valueflow/screens/meal_screen.dart';
import 'package:valueflow/screens/server_recipe_screens.dart';
import 'package:valueflow/services/settings.dart';

/// 서버 대신 정해 둔 레시피를 돌려준다. 처음 [failures]번은 서버 오류를 낸다.
class _FakeRecipeApi implements RecipeApi {
  _FakeRecipeApi(this.records, {this.failures = 0});

  final List<RecipeRecord> records;
  int failures;
  final offsets = <int>[];

  @override
  Future<RecipePage> list({
    int limit = 20,
    int offset = 0,
    String? query,
    Set<String> excludeAllergens = const {},
  }) async {
    offsets.add(offset);
    if (failures > 0) {
      failures--;
      throw const ApiException(ApiErrorType.server, '서버에 문제가 생겼어요.');
    }
    return RecipePage(
      items: records.skip(offset).take(limit).toList(),
      limit: limit,
      offset: offset,
      total: records.length,
    );
  }

  @override
  Future<RecipeRecord> detail(String recipeId) async =>
      records.firstWhere((recipe) => recipe.recipeId == recipeId);
}

/// 계약 표본(docs/설계/api_examples.json)의 레시피 상세를 바탕으로 만든다.
Map<String, dynamic> _sampleRecipe() {
  final file = File('../../docs/설계/api_examples.json');
  final json = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  final responses = json['responses'] as Map<String, dynamic>;
  return (responses['recipe_detail'] as Map<String, dynamic>)['data']
      as Map<String, dynamic>;
}

void main() {
  final sample = _sampleRecipe();

  RecipeRecord recipe(
    String id,
    String name, {
    Map<String, Object?> nutrition = const {},
    Map<String, Object?>? allergens,
  }) {
    final json = jsonDecode(jsonEncode(sample)) as Map<String, dynamic>;
    json['recipe_id'] = id;
    json['name'] = name;
    // 테스트에서는 네트워크 이미지를 쓰지 않는다.
    json['images'] = {'small': null, 'large': null};
    (json['nutrition'] as Map<String, dynamic>).addAll(nutrition);
    if (allergens != null) json['allergens'] = allergens;
    return RecipeRecord.fromJson(json);
  }

  Future<void> pump(WidgetTester tester, Widget home) async {
    tester.view.physicalSize = const Size(430, 932);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(home: home));
    await tester.pumpAndSettle();
  }

  testWidgets('서버 레시피 목록에서 상세로 이동한다', (tester) async {
    final api = _FakeRecipeApi([recipe('108', '오렌지와 당근 만남주스')]);
    await pump(tester, ServerRecipeList(api: api, settings: AppSettings()));

    expect(find.text('레시피 1개'), findsOneWidget);
    expect(find.text('오렌지와 당근 만남주스'), findsOneWidget);

    await tester.tap(find.byKey(const Key('server-recipe-108')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('server-recipe-detail')), findsOneWidget);
    expect(find.text('60 kcal'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('server-recipe-step-1')),
      300,
    );
    expect(find.text('1. 오렌지는 깨끗이 씻어 껍질을 벗긴다.'), findsOneWidget);
  });

  testWidgets('없는 영양값과 알레르기 판정을 그대로 보여준다', (tester) async {
    final api = _FakeRecipeApi([
      recipe(
        '1',
        '달걀찜',
        nutrition: {'energy_kcal': null},
        allergens: {
          'basis': 'ingredient_name',
          'detected': [
            {'allergen': '알류', 'kind': 'direct', 'evidence': []},
          ],
          'needs_check': [
            {
              'ingredient': '소스',
              'term': '소스',
              'candidates': ['우유'],
            },
          ],
          'not_determinable': [],
          'complete': false,
        },
      ),
    ]);
    await pump(
      tester,
      ServerRecipeDetail(api: api, recipeId: '1', settings: AppSettings()),
    );

    expect(find.text('정보 없음'), findsOneWidget);
    expect(find.text('0 kcal'), findsNothing);
    expect(find.text('달걀 포함'), findsOneWidget);
    expect(find.text('우유 확인 필요'), findsOneWidget);
    expect(find.textContaining('재료 분석이 끝나지 않은'), findsOneWidget);
  });

  testWidgets('목록을 못 불러오면 안내하고 다시 시도할 수 있다', (tester) async {
    final api = _FakeRecipeApi([recipe('108', '오렌지와 당근 만남주스')], failures: 1);
    await pump(tester, ServerRecipeList(api: api, settings: AppSettings()));

    expect(find.text('서버에 문제가 생겼어요.'), findsOneWidget);

    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();

    expect(find.text('오렌지와 당근 만남주스'), findsOneWidget);
    expect(api.offsets, [0, 0]);
  });

  testWidgets('20개가 넘으면 다음 페이지를 이어서 불러온다', (tester) async {
    final api = _FakeRecipeApi([
      for (var i = 1; i <= 25; i++) recipe('$i', '레시피 $i'),
    ]);
    await pump(tester, ServerRecipeList(api: api, settings: AppSettings()));

    final more = find.byKey(const Key('server-recipe-more'));
    await tester.scrollUntilVisible(more, 300);
    await tester.tap(more);
    await tester.pumpAndSettle();

    expect(api.offsets, [0, 20]);
    await tester.scrollUntilVisible(
      find.byKey(const Key('server-recipe-25')),
      300,
    );
    expect(find.byKey(const Key('server-recipe-more')), findsNothing);
  });

  testWidgets('서버가 연결되면 식단 화면에서 서버 레시피 목록을 연다', (tester) async {
    final api = _FakeRecipeApi([recipe('108', '오렌지와 당근 만남주스')]);
    await pump(
      tester,
      Scaffold(
        body: MealScreen(
          repository: const DemoRepository([], []),
          settings: AppSettings(),
          recipeApi: api,
        ),
      ),
    );

    final start = find.byKey(const Key('server-recipes-start'));
    await tester.scrollUntilVisible(start, 300);
    await tester.tap(start);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('server-recipe-list')), findsOneWidget);
  });
}
