Map<String, dynamic> intakeMap(Object? value) => value as Map<String, dynamic>;

DateTime koreanTime(DateTime instant) =>
    instant.toUtc().add(const Duration(hours: 9));
String intakeDate(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

class IntakeNutrients {
  const IntakeNutrients(this.values);
  final Map<String, double?> values;
  static const labels = {
    'energy_kcal': ('열량', 'kcal'),
    'carbohydrate_g': ('탄수화물', 'g'),
    'protein_g': ('단백질', 'g'),
    'fat_g': ('지방', 'g'),
    'sodium_mg': ('나트륨', 'mg'),
  };
  factory IntakeNutrients.fromJson(Map<String, dynamic> row) => IntakeNutrients(
    {for (final key in labels.keys) key: (row[key] as num?)?.toDouble()},
  );
}

class FoodChoice {
  const FoodChoice({
    required this.id,
    required this.revision,
    required this.name,
    this.basisText,
    this.basisUnit,
    this.servingReference,
    this.category,
    this.sourceProvider,
    this.sourceCode,
  });
  final String id, revision, name;
  final String? basisText, basisUnit, servingReference, category;
  final String? sourceProvider, sourceCode;
  bool get hasServing => _validServing(servingReference);
  static bool _validServing(String? reference) {
    final match = RegExp(
      r'^\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(g|kg|mL|ml|L)\s*$',
    ).firstMatch(reference ?? '');
    final amount = match == null
        ? null
        : double.tryParse(match[1]!.replaceAll(',', ''));
    return amount != null && amount.isFinite && amount > 0;
  }

  factory FoodChoice.fromJson(Map<String, dynamic> row) {
    final basis = intakeMap(row['basis']), source = intakeMap(row['source']);
    String? reference;
    for (final candidate in [
      row['dish_serving_text'],
      row['serving_ref_text'],
    ]) {
      if (candidate is String && _validServing(candidate)) {
        reference = candidate;
        break;
      }
    }
    return FoodChoice(
      id: row['food_id'] as String,
      revision: source['revision_id'] as String,
      name: row['name'] as String,
      basisText: basis['text'] as String?,
      basisUnit: basis['unit'] as String?,
      category: row['category'] as String?,
      servingReference: reference,
      sourceProvider: source['provider'] as String?,
      sourceCode: source['food_code'] as String?,
    );
  }
  Map<String, dynamic> toStorage() => {
    'id': id,
    'revision': revision,
    'name': name,
    'basis': basisText,
    'unit': basisUnit,
    'serving': servingReference,
    'category': category,
    if (sourceProvider != null) 'provider': sourceProvider,
    if (sourceCode != null) 'code': sourceCode,
  };
  factory FoodChoice.fromStorage(Map<String, dynamic> row) => FoodChoice(
    id: row['id'] as String,
    revision: row['revision'] as String,
    name: row['name'] as String,
    basisText: row['basis'] as String?,
    basisUnit: row['unit'] as String?,
    servingReference: row['serving'] as String?,
    category: row['category'] as String?,
    sourceProvider: row['provider'] as String?,
    sourceCode: row['code'] as String?,
  );
}

class FoodOrigin {
  const FoodOrigin({
    required this.method,
    required this.quantityBasis,
    this.recognizedName,
    this.ingredientName,
    this.referenceRecipeName,
  });
  final String method, quantityBasis;
  final String? recognizedName, ingredientName, referenceRecipeName;
  Map<String, dynamic> toJson() => {
    'method': method,
    'quantity_basis': quantityBasis,
    if (recognizedName != null) 'recognized_name': recognizedName,
    if (ingredientName != null) 'ingredient_name': ingredientName,
    if (referenceRecipeName != null)
      'reference_recipe_name': referenceRecipeName,
  };
  factory FoodOrigin.fromJson(Map<String, dynamic> row) {
    final method = row['method'] as String,
        basis = row['quantity_basis'] as String;
    if (!{
          'manual',
          'photo',
          'similar_food',
          'ingredient_estimate',
        }.contains(method) ||
        !{
          'user_entered',
          'source_serving',
          'ai_estimate',
          'user_adjusted',
        }.contains(basis)) {
      throw const FormatException('Unknown input context');
    }
    final result = FoodOrigin(
      method: method,
      quantityBasis: basis,
      recognizedName: row['recognized_name'] as String?,
      ingredientName: row['ingredient_name'] as String?,
      referenceRecipeName: row['reference_recipe_name'] as String?,
    );
    if ((result.method != 'manual' && result.recognizedName == null) ||
        (result.method == 'ingredient_estimate' &&
            result.ingredientName == null) ||
        (result.method != 'ingredient_estimate' &&
            (result.ingredientName != null ||
                result.referenceRecipeName != null))) {
      throw const FormatException('Inconsistent input context');
    }
    return result;
  }
  FoodOrigin adjusted() => FoodOrigin(
    method: method,
    quantityBasis: 'user_adjusted',
    recognizedName: recognizedName,
    ingredientName: ingredientName,
    referenceRecipeName: referenceRecipeName,
  );
}

class ExcludedIngredient {
  const ExcludedIngredient(this.dishName, this.name, this.reason);
  final String dishName, name, reason;
  Map<String, dynamic> toJson() => {
    'dish_name': dishName,
    'ingredient_name': name,
    'reason': reason,
  };
  factory ExcludedIngredient.fromJson(Map<String, dynamic> row) {
    final result = ExcludedIngredient(
      row['dish_name'] as String,
      row['ingredient_name'] as String,
      row['reason'] as String,
    );
    if (!{'user_excluded', 'unmatched', 'water'}.contains(result.reason)) {
      throw const FormatException('Unknown exclusion context');
    }
    return result;
  }
}

class AnalysisContext {
  const AnalysisContext(this.excluded);
  final List<ExcludedIngredient> excluded;
  bool get partial => excluded.any((item) => item.reason != 'water');
  Map<String, dynamic> toJson() => {
    'excluded_ingredients': [for (final item in excluded) item.toJson()],
  };
  factory AnalysisContext.fromJson(Map<String, dynamic> row) {
    final result = AnalysisContext(
      List.unmodifiable([
        for (final item in row['excluded_ingredients'] as List)
          ExcludedIngredient.fromJson(intakeMap(item)),
      ]),
    );
    if (result.excluded.length > 48) {
      throw const FormatException('Too many exclusions');
    }
    return result;
  }
}

class IngredientReviewSelection {
  const IngredientReviewSelection(this.items, this.excluded);
  final List<FoodSelection> items;
  final List<ExcludedIngredient> excluded;
}

class FoodSelection {
  const FoodSelection(
    this.food,
    this.amount,
    this.unit, {
    this.estimated = false,
    this.origin,
  });
  final FoodChoice food;
  final double amount;
  final String unit;
  final bool estimated;
  final FoodOrigin? origin;
  Map<String, dynamic> toJson() => {
    'food_id': food.id,
    'revision_id': food.revision,
    'amount': amount,
    'unit': unit,
    if (estimated) 'amount_is_estimate': true,
    if (origin != null) 'origin': origin!.toJson(),
  };
  Map<String, dynamic> toStorage() => {
    'food': food.toStorage(),
    'amount': amount,
    'unit': unit,
    if (estimated) 'estimated': true,
    if (origin != null) 'origin': origin!.toJson(),
  };
  factory FoodSelection.fromStorage(Map<String, dynamic> row) {
    final result = FoodSelection(
      FoodChoice.fromStorage(intakeMap(row['food'])),
      (row['amount'] as num).toDouble(),
      row['unit'] as String,
      estimated: row['estimated'] as bool? ?? false,
      origin: row['origin'] == null
          ? null
          : FoodOrigin.fromJson(intakeMap(row['origin'])),
    );
    if (!result.amount.isFinite ||
        result.amount <= 0 ||
        result.amount > 10000 ||
        !{'g', 'mL', '인분'}.contains(result.unit)) {
      throw const FormatException('Invalid stored portion');
    }
    return result;
  }
}

class FoodPage {
  const FoodPage(this.items, this.total, this.offset);
  final List<FoodChoice> items;
  final int total, offset;
}

class IntakeTotal {
  const IntakeTotal({
    required this.nutrients,
    required this.complete,
    required this.approximate,
    required this.missing,
  });
  final IntakeNutrients nutrients;
  final bool complete, missing;
  final int approximate;
  factory IntakeTotal.fromJson(Map<String, dynamic> row) => IntakeTotal(
    nutrients: IntakeNutrients.fromJson(intakeMap(row['nutrients'])),
    complete: row['complete'] as bool,
    approximate: row['approx_ml_items'] as int,
    missing: intakeMap(row['missing_items']).isNotEmpty,
  );
}

class IntakePreview {
  const IntakePreview(this.total, this.notes, this.invalid);
  final IntakeTotal total;
  final List<String> notes;
  final Set<int> invalid;
  static bool _recordable(Map<String, dynamic> item) {
    final amount = (item['amount'] as num?)?.toDouble();
    return {'computed', 'approx_ml'}.contains(item['status']) &&
        amount != null &&
        amount.isFinite &&
        amount >= 0.001 &&
        amount <= 9999999.999 &&
        (amount * 1000 - (amount * 1000).round()).abs() <= 0.000001;
  }

  factory IntakePreview.fromJson(Map<String, dynamic> row) {
    final items = row['items'] as List;
    return IntakePreview(
      IntakeTotal.fromJson(intakeMap(row['total'])),
      [
        for (final item in items)
          if ((intakeMap(item)['note'] as String).isNotEmpty)
            '${intakeMap(item)['food_name']}: ${intakeMap(item)['note']}',
      ],
      {
        for (var i = 0; i < items.length; i++)
          if (!_recordable(intakeMap(items[i]))) i,
      },
    );
  }
}

class SavedIntake {
  const SavedIntake({
    required this.id,
    required this.version,
    required this.eatenAt,
    required this.total,
    this.items = const [],
    required this.legacy,
    this.analysisContext,
    this.containsEstimates = false,
  });
  final String id;
  final int version;
  final DateTime eatenAt;
  final IntakeTotal total;
  final List<FoodSelection> items;
  final bool legacy;
  final AnalysisContext? analysisContext;
  final bool containsEstimates;
  factory SavedIntake.fromJson(Map<String, dynamic> row) => SavedIntake(
    id: row['id'] as String,
    version: row['version'] as int,
    eatenAt: DateTime.parse(row['eaten_at'] as String).toUtc(),
    total: IntakeTotal.fromJson(intakeMap(row['total'])),
    legacy: row['legacy_snapshot_missing'] as bool,
    containsEstimates: row['contains_estimates'] as bool? ?? false,
    analysisContext: row['analysis_context'] == null
        ? null
        : AnalysisContext.fromJson(intakeMap(row['analysis_context'])),
    items: [
      for (final value in (row['items'] as List? ?? []))
        _selection(intakeMap(value)),
    ],
  );
  static FoodSelection _selection(Map<String, dynamic> row) {
    final calculation = row['calculation'] as Map<String, dynamic>?,
        basis = calculation?['basis'] as Map<String, dynamic>?;
    final serving = calculation?['serving'] as Map<String, dynamic>?,
        input = calculation?['input'] as Map<String, dynamic>?;
    final source = calculation?['source'] as Map<String, dynamic>?;
    final food = FoodChoice(
      id: row['food_id'] as String,
      revision: row['revision_id'] as String,
      name: row['name'] as String,
      basisText: basis?['text'] as String?,
      basisUnit: basis?['unit'] as String?,
      servingReference: serving?['text'] as String?,
      sourceProvider: source?['provider'] as String?,
      sourceCode: row['food_code'] as String?,
    );
    // Preserve the user's confirmed unit where evidence exists; old records retain saved g/mL.
    final unit = input?['unit'];
    final original =
        {'g', 'mL', '인분'}.contains(unit) && (unit != '인분' || food.hasServing);
    return FoodSelection(
      food,
      ((original ? input!['amount'] : row['amount']) as num).toDouble(),
      (original ? unit : row['amount_unit']) as String,
      estimated: calculation?['amount_is_estimate'] as bool? ?? false,
      origin: calculation?['origin'] == null
          ? null
          : FoodOrigin.fromJson(intakeMap(calculation!['origin'])),
    );
  }
}

class IntakePage {
  const IntakePage(this.items, this.total, this.offset);
  final List<SavedIntake> items;
  final int total, offset;
}

class PendingIntake {
  const PendingIntake(
    this.owner,
    this.key,
    this.eatenAt,
    this.items, {
    this.analysisContext,
  });
  final String owner, key;
  final DateTime eatenAt;
  final List<FoodSelection> items;
  final AnalysisContext? analysisContext;
  Map<String, dynamic> get body => {
    'eaten_at': eatenAt.toUtc().toIso8601String(),
    'items': items.map((item) => item.toJson()).toList(),
    if (analysisContext != null) 'analysis_context': analysisContext!.toJson(),
  };
  Map<String, dynamic> toStorage() => {
    'version': 1,
    'owner': owner,
    'key': key,
    'eaten_at': eatenAt.toUtc().toIso8601String(),
    'items': items.map((item) => item.toStorage()).toList(),
    if (analysisContext != null) 'analysis_context': analysisContext!.toJson(),
  };
  factory PendingIntake.fromStorage(Map<String, dynamic> row) {
    if (row['version'] != 1) {
      throw const FormatException('Unknown pending request version');
    }
    final result = PendingIntake(
      row['owner'] as String,
      row['key'] as String,
      DateTime.parse(row['eaten_at'] as String).toUtc(),
      [
        for (final item in row['items'] as List)
          FoodSelection.fromStorage(intakeMap(item)),
      ],
      analysisContext: row['analysis_context'] == null
          ? null
          : AnalysisContext.fromJson(intakeMap(row['analysis_context'])),
    );
    if (!RegExp(r'^[a-f0-9]{32}$').hasMatch(result.key) ||
        result.items.isEmpty ||
        result.items.length > 30) {
      throw const FormatException('Invalid pending request');
    }
    return result;
  }
}
