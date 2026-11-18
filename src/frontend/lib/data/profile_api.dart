import 'package:flutter/foundation.dart';

import '../core/network/api_client.dart';

class ProfilePreferences {
  const ProfilePreferences({
    this.age,
    this.region,
    this.district,
    this.livesAlone,
    this.softFood,
    this.preferredIngredients = const [],
    this.excludedIngredients = const [],
    this.excludeAllergens = const [],
  });

  final int? age;
  final String? region, district;
  final bool? livesAlone, softFood;
  final List<String> preferredIngredients,
      excludedIngredients,
      excludeAllergens;

  factory ProfilePreferences.fromJson(Map<String, dynamic> json) {
    T? optional<T>(String key) {
      final value = json[key];
      if (value == null) return null;
      if (value is T) return value;
      throw FormatException('Invalid preference: $key');
    }

    List<String> strings(String key) {
      final value = json[key];
      if (value is! List || value.any((entry) => entry is! String)) {
        throw FormatException('Invalid preference: $key');
      }
      return List<String>.from(value);
    }

    return ProfilePreferences(
      age: optional<int>('age'),
      region: optional<String>('region'),
      district: optional<String>('district'),
      livesAlone: optional<bool>('lives_alone'),
      softFood: optional<bool>('soft_food'),
      preferredIngredients: strings('preferred_ingredients'),
      excludedIngredients: strings('excluded_ingredients'),
      excludeAllergens: strings('exclude_allergens'),
    );
  }

  Map<String, Object?> toJson() => {
    'age': age,
    'region': region,
    'district': district,
    'lives_alone': livesAlone,
    'soft_food': softFood,
    'preferred_ingredients': preferredIngredients,
    'excluded_ingredients': excludedIngredients,
    'exclude_allergens': excludeAllergens,
  };
}

class ProfileApi {
  const ProfileApi(this._client);

  final ApiClient _client;
  static const _path = '/api/v1/profile';

  Future<ProfilePreferences?> load(String token) =>
      _client.get(_path, token: token, parse: _preferences);

  Future<ProfilePreferences> save(
    String token,
    ProfilePreferences preferences, {
    required ProfilePreferences? previous,
  }) async {
    final changes = preferences.toJson();
    if (previous != null) {
      final original = previous.toJson();
      changes.removeWhere((key, value) {
        final oldValue = original[key];
        if (value is List<String> && oldValue is List<String>) {
          return listEquals(value, oldValue);
        }
        return value == oldValue;
      });
      if (changes.isEmpty) return previous;
    }
    return _client.patch(
      _path,
      token: token,
      body: {if (previous == null) 'consent': true, 'preferences': changes},
      parse: (body) =>
          _preferences(body) ??
          (throw const FormatException('Missing profile')),
    );
  }

  Future<void> withdraw(String token) => _client.patch<void>(
    _path,
    token: token,
    body: {'consent': false},
    parse: (body) {
      if (_preferences(body) != null) {
        throw const FormatException('Expected cleared profile');
      }
    },
  );

  static ProfilePreferences? _preferences(Object? body) {
    if (body is! Map<String, dynamic> || !body.containsKey('data')) {
      throw const FormatException('Missing profile response');
    }
    final data = body['data'];
    if (data == null) return null;
    final preferences = data is Map<String, dynamic>
        ? data['preferences']
        : null;
    if (preferences is! Map<String, dynamic>) {
      throw const FormatException('Missing profile preferences');
    }
    return ProfilePreferences.fromJson(preferences);
  }
}
