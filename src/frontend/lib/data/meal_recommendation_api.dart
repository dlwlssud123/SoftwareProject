import '../core/network/api_client.dart';
import '../models/recommendations.dart';
import 'guest_session.dart';

class MealRecommendationApi {
  MealRecommendationApi(
    this._client, {
    String? guestStorageKey,
    GuestSession? session,
  }) : _session = session ?? GuestSession(_client, storageKey: guestStorageKey);

  final ApiClient _client;
  final GuestSession _session;

  Future<MealRecommendations> recommend(UserProfile profile, MealTime time) =>
      _session.request((token) => _recommend(profile, time, token));

  Future<MealRecommendations> _recommend(
    UserProfile profile,
    MealTime time,
    String token,
  ) => _client.post(
    '/api/v1/meal/recommendations',
    token: token,
    body: {
      'meal_time': time.name,
      'soft_food': profile.softFood,
      if (profile.simpleCooking) 'simple_cooking': true,
      if (profile.preferredIngredients.isNotEmpty)
        'preferred_ingredients': profile.preferredIngredients.toList(),
      'health_conditions': [
        if (profile.conditions.contains('고혈압')) 'hypertension',
        if (profile.conditions.contains('당뇨')) 'diabetes',
      ],
      'exclude_allergens': [
        for (final name in profile.allergies) name == '달걀' ? '알류' : name,
      ],
    },
    parse: (body) {
      final data = _object(_object(body)['data']);
      return MealRecommendations([
        for (final entry in _list(data['items'])) _match(_object(entry)),
      ], _strings(data['warnings']));
    },
  );

  static RecipeMatch _match(Map<String, dynamic> json) {
    final item = _object(json['item']);
    final nutrition = _object(item['nutrition']);
    final allergens = _object(item['allergens']);
    final image = _object(item['images'])['small'];
    final preferences = json['matched_preferences'] == null
        ? null
        : _strings(json['matched_preferences']);
    return RecipeMatch(
      Recipe(
        id: _string(item['recipe_id']),
        name: _string(item['name']),
        ingredients: _optionalString(item['ingredients_text']) ?? '',
        steps: [
          for (final entry in _list(item['steps'])) _step(_object(entry)),
        ],
        calories: _number(nutrition['energy_kcal']),
        sodium: _number(nutrition['sodium_mg']),
        protein: _number(nutrition['protein_g']),
        carbs: _number(nutrition['carbohydrate_g']),
        fat: _number(nutrition['fat_g']),
        method: _optionalString(item['cooking_method']) ?? '',
        allergens: {
          for (final entry in _list(allergens['detected']))
            _allergen(_object(entry)),
        },
        soft: false,
        fromServer: true,
        revisionId: _optionalString(
          item['source'] == null
              ? null
              : _object(item['source'])['revision_id'],
        ),
        imageUrl: _httpsUrl(image)?.toString(),
      ),
      _strings(json['reasons']),
      softMatch: preferences?.contains('soft_food'),
      simpleMatch: preferences?.contains('simple_cooking'),
      ingredientCount: _list(item['ingredients'] ?? const []).length,
      seasonal: [
        for (final entry in _list(json['seasonal_ingredients'] ?? const []))
          _seasonal(_object(entry)),
      ],
    );
  }

  static SeasonalIngredient _seasonal(Map<String, dynamic> item) {
    final url = _httpsUrl(item['shopping_search_url']);
    return SeasonalIngredient(
      _string(item['name']),
      url?.host == 'www.coupang.com' ? url : null,
    );
  }

  static String _step(Map<String, dynamic> step) {
    final number = step['no'];
    if (number is! int) throw const FormatException('Invalid step number');
    return '$number. ${_string(step['text'])}';
  }

  static String _allergen(Map<String, dynamic> item) {
    final name = _string(item['allergen']);
    return name == '알류' ? '달걀' : name;
  }

  static Map<String, dynamic> _object(Object? value) =>
      value is Map<String, dynamic>
      ? value
      : throw const FormatException('Expected object');
  static List<dynamic> _list(Object? value) =>
      value is List ? value : throw const FormatException('Expected list');
  static String _string(Object? value) =>
      value is String ? value : throw const FormatException('Expected text');
  static String? _optionalString(Object? value) =>
      value == null ? null : _string(value);
  static List<String> _strings(Object? value) =>
      _list(value).map(_string).toList();
  static double? _number(Object? value) => switch (value) {
    null => null,
    num value => value.toDouble(),
    _ => throw const FormatException('Expected nutrition number'),
  };
  static Uri? _httpsUrl(Object? value) {
    final uri = Uri.tryParse(_optionalString(value) ?? '');
    return uri != null &&
            uri.scheme == 'https' &&
            uri.host.isNotEmpty &&
            uri.userInfo.isEmpty
        ? uri
        : null;
  }
}
