import '../core/network/api_client.dart';
import 'guest_session.dart';

enum MealSlot {
  breakfast('아침'),
  lunch('점심'),
  dinner('저녁'),
  snack('간식'),
  special('특별 메뉴');

  const MealSlot(this.label);
  final String label;
}

class RecipeChoice {
  const RecipeChoice(this.id, this.name, {this.revisionId});

  final String id, name;
  final String? revisionId;
}

class PlanEntry {
  const PlanEntry(this.recipe, {required this.isActive});

  final RecipeChoice recipe;
  final bool isActive;
}

class SavedRecipeItem {
  const SavedRecipeItem(this.id, this.name);

  final String id;
  final String? name;
}

class SavedRecipesPage {
  const SavedRecipesPage(this.items, this.total);

  final List<SavedRecipeItem> items;
  final int total;
}

class RecipeLibraryApi {
  const RecipeLibraryApi(this._client, this._session);

  static const _plans = '/api/v1/meal-plans';
  static const _saved = '/api/v1/saved-recipes';
  final ApiClient _client;
  final GuestSession _session;

  Future<Map<MealSlot, PlanEntry>> plan(DateTime date) => _session.request(
    (token) => _client.get(
      '$_plans/${_date(date)}',
      token: token,
      parse: (body) => _read(body, (data) {
        return {
          for (final row
              in (data['items'] as List).cast<Map<String, dynamic>>())
            MealSlot.values.byName(row['meal_slot'] as String): PlanEntry(
              RecipeChoice(
                row['recipe_id'] as String,
                row['name'] as String,
                revisionId: row['recipe_revision_id'] as String,
              ),
              isActive: row['is_active'] as bool,
            ),
        };
      }),
    ),
  );

  Future<void> putMeal(DateTime date, MealSlot slot, RecipeChoice recipe) =>
      _session.request(
        (token) => _client.put<void>(
          '$_plans/${_date(date)}/${slot.name}',
          token: token,
          body: {
            'recipe_id': recipe.id,
            if (recipe.revisionId != null)
              'recipe_revision_id': recipe.revisionId,
          },
          parse: (_) {},
        ),
      );

  Future<void> removeMeal(DateTime date, MealSlot slot) => _session.request(
    (token) =>
        _client.delete('$_plans/${_date(date)}/${slot.name}', token: token),
  );

  Future<SavedRecipesPage> saved({int offset = 0}) => _session.request(
    (token) => _client.get(
      _saved,
      token: token,
      query: {'offset': offset, 'limit': 20},
      parse: (body) => _read(
        body,
        (data) => SavedRecipesPage([
          for (final row
              in (data['items'] as List).cast<Map<String, dynamic>>())
            SavedRecipeItem(row['recipe_id'] as String, row['name'] as String?),
        ], data['total'] as int),
      ),
    ),
  );

  Future<bool> isSaved(String id) => _session.request(
    (token) => _client.get(
      '$_saved/${Uri.encodeComponent(id)}',
      token: token,
      parse: (body) => _read(body, (data) => data['saved'] as bool),
    ),
  );

  Future<void> setSaved(String id, bool saved) {
    final path = '$_saved/${Uri.encodeComponent(id)}';
    return _session.request(
      (token) => saved
          ? _client.put<void>(path, token: token, parse: (_) {})
          : _client.delete(path, token: token),
    );
  }

  static String _date(DateTime date) => date.toIso8601String().split('T').first;

  static T _read<T>(Object? body, T Function(Map<String, dynamic>) decode) {
    try {
      return decode(
        (body as Map<String, dynamic>)['data'] as Map<String, dynamic>,
      );
    } on TypeError {
      throw const FormatException('Invalid personal recipe response');
    } on ArgumentError {
      throw const FormatException('Invalid meal slot');
    }
  }
}
