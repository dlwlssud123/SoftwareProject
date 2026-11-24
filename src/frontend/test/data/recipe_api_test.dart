import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/recipe_api.dart';
import 'package:valueflow/models/recipe_record.dart';

/// 실제 서버 대신 정해 둔 응답을 돌려주고, 보낸 요청을 기록한다.
class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.status, this.body);

  final int status;
  final Object body;
  RequestOptions? lastRequest;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    lastRequest = options;
    return ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

/// 백엔드가 테스트로 대조하는 계약 표본(docs/설계/api_examples.json)을 그대로 읽는다.
/// 표본이 바뀌면 이 테스트도 함께 확인된다.
Map<String, dynamic> _examples() {
  final file = File('../../docs/설계/api_examples.json');
  if (!file.existsSync()) {
    fail('계약 표본을 찾지 못했습니다: ${file.absolute.path}');
  }
  final json = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  return json['responses'] as Map<String, dynamic>;
}

Map<String, dynamic> _copy(Object? json) =>
    jsonDecode(jsonEncode(json)) as Map<String, dynamic>;

void main() {
  final examples = _examples();

  (RecipeApi, _FakeAdapter) apiReturning(int status, Object body) {
    final adapter = _FakeAdapter(status, body);
    final dio = Dio(BaseOptions(baseUrl: 'http://test.local'))
      ..httpClientAdapter = adapter;
    return (RecipeApi(ApiClient(dio: dio)), adapter);
  }

  test('목록 표본을 읽고 /api/v1/recipes로 요청한다', () async {
    final (api, adapter) = apiReturning(200, examples['recipe_list'] as Object);

    final page = await api.list();

    expect(adapter.lastRequest!.uri.path, '/api/v1/recipes');
    expect(adapter.lastRequest!.uri.queryParameters, {
      'limit': '20',
      'offset': '0',
    });
    expect(page.total, 1);
    expect(page.hasMore, isFalse);
    final recipe = page.items.single;
    expect(recipe.recipeId, '108');
    expect(recipe.name, '오렌지와 당근 만남주스');
    expect(recipe.steps, hasLength(6));
    expect(recipe.steps.first.no, 1);
    expect(recipe.ingredients.map((i) => i.name), ['당근', '오렌지']);
    expect(recipe.nutrition.energyKcal, 60.0);
    expect(recipe.nutrition.sodiumMg, 76.0);
    expect(recipe.allergens.notDeterminable, {'아황산류'});
    expect(recipe.allergens.complete, isTrue);
  });

  test('알레르기 제외는 서버 표기로 바꿔 같은 키를 반복해 보낸다', () async {
    final (api, adapter) = apiReturning(200, examples['empty_list'] as Object);

    await api.list(query: '  죽 ', excludeAllergens: {'달걀', '우유'});

    final uri = adapter.lastRequest!.uri;
    expect(uri.queryParametersAll['exclude_allergens'], ['알류', '우유']);
    expect(uri.queryParameters['q'], '죽');
  });

  test('빈 목록 표본은 항목 0개로 읽는다', () async {
    final (api, _) = apiReturning(200, examples['empty_list'] as Object);

    final page = await api.list();

    expect(page.items, isEmpty);
    expect(page.total, 0);
  });

  test('상세 표본을 읽고 /api/v1/recipes/{id}로 요청한다', () async {
    final (api, adapter) = apiReturning(
      200,
      examples['recipe_detail'] as Object,
    );

    final recipe = await api.detail('108');

    expect(adapter.lastRequest!.uri.path, '/api/v1/recipes/108');
    expect(recipe.recipeId, '108');
    expect(recipe.qualityStatus, 'ok');
    expect(recipe.imageLarge, startsWith('https://'));
  });

  test('누락된 영양값은 0이 아니라 null로 남긴다', () async {
    final body = _copy(examples['recipe_detail']);
    (body['data']['nutrition'] as Map)['energy_kcal'] = null;
    final (api, _) = apiReturning(200, body);

    final recipe = await api.detail('108');

    expect(recipe.nutrition.energyKcal, isNull);
    expect(recipe.nutrition.proteinG, 1.0);
  });

  test('검출 알레르기와 확인 필요 후보를 모두 피해야 할 항목으로 본다', () async {
    final body = _copy(examples['recipe_detail']);
    (body['data'] as Map)['allergens'] = {
      'basis': 'ingredient_name',
      'detected': [
        {
          'allergen': '알류',
          'kind': 'direct',
          'evidence': [
            {'ingredient': '달걀', 'term': '달걀', 'kind': 'direct'},
          ],
        },
      ],
      'needs_check': [
        {
          'ingredient': '소스',
          'term': '소스',
          'candidates': ['우유', '대두'],
        },
      ],
      'not_determinable': [],
      'complete': false,
    };
    final (api, _) = apiReturning(200, body);

    final allergens = (await api.detail('108')).allergens;

    expect(allergens.detected, {'알류'});
    expect(allergens.toAvoid, {'알류', '우유', '대두'});
    expect(allergens.complete, isFalse);
    expect(allergens.detected.map(appAllergenName), ['달걀']);
  });

  test('서버 오류 표본은 안내 문구와 재시도 여부를 그대로 전달한다', () async {
    final body = examples['database_unavailable'] as Map<String, dynamic>;
    final (api, _) = apiReturning(503, body);

    await expectLater(
      api.list(),
      throwsA(
        isA<ApiException>()
            .having((e) => e.type, 'type', ApiErrorType.server)
            .having(
              (e) => e.message,
              'message',
              (body['error'] as Map)['message'],
            )
            .having((e) => e.canRetry, 'canRetry', isTrue),
      ),
    );
  });

  test('data가 없는 응답은 형식 오류로 처리한다', () async {
    final (api, _) = apiReturning(200, {'meta': {}});

    await expectLater(
      api.detail('108'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.type,
          'type',
          ApiErrorType.badResponse,
        ),
      ),
    );
  });

  test('필드 형식이 계약과 다르면 형식 오류로 처리한다', () async {
    final body = _copy(examples['recipe_detail']);
    (body['data'] as Map)['recipe_id'] = 108;
    final (api, _) = apiReturning(200, body);

    await expectLater(
      api.detail('108'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.type,
          'type',
          ApiErrorType.badResponse,
        ),
      ),
    );
  });

  /// food_nutrition_contract.md 3.4의 예시(3282 어린잎채소 건두부말이).
  Map<String, Object?> contractComputedNutrition() => {
    'basis': 'whole_recipe',
    'servings': 2.0,
    'total': {
      'energy_kcal': 1244.0,
      'carbohydrate_g': 73.0,
      'protein_g': 63.6,
      'fat_g': 78.1,
      'sodium_mg': 752.8,
      'sugars_g': 42.2,
      'fiber_g': 5.3,
      'sat_fat_g': 23.5,
      'cholesterol_mg': 59.2,
      'potassium_mg': 750.6,
      'calcium_mg': 1102.9,
    },
    'per_serving': {
      'energy_kcal': 622.0,
      'carbohydrate_g': 36.5,
      'protein_g': 31.8,
      'fat_g': 39.0,
      'sodium_mg': 376.4,
      'sugars_g': 21.1,
      'fiber_g': 2.7,
      'sat_fat_g': 11.8,
      'cholesterol_mg': 29.6,
      'potassium_mg': 375.3,
      'calcium_mg': 551.5,
    },
    'partial_nutrients': ['cholesterol_mg', 'potassium_mg'],
    'complete': true,
    'density': {
      'sodium_mg_per_1000kcal': 605.1,
      'carbohydrate_energy_pct': 23.5,
      'protein_energy_pct': 20.5,
      'fat_energy_pct': 56.5,
    },
    'notices': [
      {
        'code': 'estimated_amount',
        'label': '일부 재료는 양을 추정했어요',
        'items': [
          {'name': '건두부', 'amount_text': '(10장)', 'grams': 130.0},
          {'name': '후춧가루', 'amount_text': '(약간)', 'grams': 0.02},
        ],
      },
    ],
    'version': 'recipe-food-map-v8',
  };

  test('재료로 계산한 영양(computed_nutrition)을 원문 표기와 따로 읽는다', () async {
    final body = _copy(examples['recipe_detail']);
    (body['data'] as Map)['computed_nutrition'] = contractComputedNutrition();
    final (api, _) = apiReturning(200, body);

    final recipe = await api.detail('108');
    final computed = recipe.computedNutrition!;

    expect(computed.servings, 2.0);
    expect(computed.total.energyKcal, 1244.0);
    expect(computed.perServing!.energyKcal, 622.0);
    expect(computed.shown.sodiumMg, 376.4);
    expect(computed.partialNutrients, {'cholesterol_mg', 'potassium_mg'});
    expect(computed.density.sodiumMgPer1000kcal, 605.1);
    expect(computed.notices.single.label, '일부 재료는 양을 추정했어요');
    expect(computed.notices.single.itemNames, ['건두부 (10장)', '후춧가루 (약간)']);
    // 원문 1인분 표기는 그대로 남는다.
    expect(recipe.nutrition.energyKcal, 60.0);
  });

  test('N인분 표기가 없으면 1인분을 만들지 않고 전체 합계를 보여준다', () async {
    final body = _copy(examples['recipe_detail']);
    (body['data'] as Map)['computed_nutrition'] = contractComputedNutrition()
      ..['servings'] = null
      ..['per_serving'] = null;
    final (api, _) = apiReturning(200, body);

    final computed = (await api.detail('108')).computedNutrition!;

    expect(computed.perServing, isNull);
    expect(computed.shown.energyKcal, 1244.0);
  });

  test('매핑 전(null)이거나 칸이 없으면 계산 영양 없이 읽는다', () async {
    final withNull = _copy(examples['recipe_detail']);
    (withNull['data'] as Map)['computed_nutrition'] = null;
    final (nullApi, _) = apiReturning(200, withNull);
    expect((await nullApi.detail('108')).computedNutrition, isNull);

    // 현재 계약 표본(api_examples.json)에는 이 칸이 없다.
    final (missingApi, _) = apiReturning(
      200,
      examples['recipe_detail'] as Object,
    );
    expect((await missingApi.detail('108')).computedNutrition, isNull);
  });

  test('계산 영양 형식이 계약과 다르면 형식 오류로 처리한다', () async {
    final body = _copy(examples['recipe_detail']);
    (body['data'] as Map)['computed_nutrition'] = contractComputedNutrition()
      ..remove('total');
    final (api, _) = apiReturning(200, body);

    await expectLater(
      api.detail('108'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.type,
          'type',
          ApiErrorType.badResponse,
        ),
      ),
    );
  });
}
