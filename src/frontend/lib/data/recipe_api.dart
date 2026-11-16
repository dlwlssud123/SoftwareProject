import 'package:dio/dio.dart' show ListFormat, ListParam;

import '../core/network/api_client.dart';
import '../models/recipe_record.dart';

/// 레시피 목록 한 페이지.
class RecipePage {
  const RecipePage({
    required this.items,
    required this.limit,
    required this.offset,
    required this.total,
  });

  final List<RecipeRecord> items;
  final int limit;
  final int offset;
  final int total;

  bool get hasMore => offset + items.length < total;

  factory RecipePage.fromJson(Map<String, dynamic> json) => RecipePage(
    items: [
      for (final row in json['items'] as List)
        RecipeRecord.fromJson(row as Map<String, dynamic>),
    ],
    limit: json['limit'] as int,
    offset: json['offset'] as int,
    total: json['total'] as int,
  );
}

/// 서버 레시피 API(`GET /api/v1/recipes`, `GET /api/v1/recipes/{id}`).
///
/// 실패하면 [ApiClient]가 변환한 ApiException을 던진다.
class RecipeApi {
  const RecipeApi(this._client);

  final ApiClient _client;

  /// [excludeAllergens]는 앱 표기(예: 달걀)로 받아 서버 표기로 바꿔 보낸다.
  Future<RecipePage> list({
    int limit = 20,
    int offset = 0,
    String? query,
    Set<String> excludeAllergens = const {},
  }) {
    final keyword = query?.trim();
    return _client.get(
      '/api/v1/recipes',
      query: {
        'limit': limit,
        'offset': offset,
        if (keyword != null && keyword.isNotEmpty) 'q': keyword,
        // 계약: ?exclude_allergens=알류&exclude_allergens=우유 처럼 같은 키 반복
        if (excludeAllergens.isNotEmpty)
          'exclude_allergens': ListParam<String>([
            for (final name in excludeAllergens) serverAllergenName(name),
          ], ListFormat.multi),
      },
      parse: (body) => _readData(body, RecipePage.fromJson),
    );
  }

  Future<RecipeRecord> detail(String recipeId) => _client.get(
    '/api/v1/recipes/${Uri.encodeComponent(recipeId)}',
    parse: (body) => _readData(body, RecipeRecord.fromJson),
  );
}

/// 공통 응답 `{data, meta}`에서 data를 꺼내 변환한다.
/// 형식이 계약과 다르면 FormatException → ApiClient가 badResponse로 바꾼다.
T _readData<T>(Object? body, T Function(Map<String, dynamic>) convert) {
  if (body is! Map<String, dynamic>) {
    throw const FormatException('응답이 JSON 객체가 아닙니다.');
  }
  final data = body['data'];
  if (data is! Map<String, dynamic>) {
    throw const FormatException('응답에 data가 없습니다.');
  }
  try {
    return convert(data);
  } on TypeError {
    throw const FormatException('응답 필드 형식이 계약과 다릅니다.');
  }
}
