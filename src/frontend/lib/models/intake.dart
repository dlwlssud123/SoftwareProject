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
  });
  final String id, revision, name;
  final String? basisText, basisUnit, servingReference, category;
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
  };
  factory FoodChoice.fromStorage(Map<String, dynamic> row) => FoodChoice(
    id: row['id'] as String,
    revision: row['revision'] as String,
    name: row['name'] as String,
    basisText: row['basis'] as String?,
    basisUnit: row['unit'] as String?,
    servingReference: row['serving'] as String?,
    category: row['category'] as String?,
  );
}

class FoodSelection {
  const FoodSelection(
    this.food,
    this.amount,
    this.unit, {
    this.estimated = false,
  });
  final FoodChoice food;
  final double amount;
  final String unit;
  final bool estimated;
  Map<String, dynamic> toJson() => {
    'food_id': food.id,
    'revision_id': food.revision,
    'amount': amount,
    'unit': unit,
    if (estimated) 'amount_is_estimate': true,
  };
  Map<String, dynamic> toStorage() => {
    'food': food.toStorage(),
    'amount': amount,
    'unit': unit,
    if (estimated) 'estimated': true,
  };
  factory FoodSelection.fromStorage(Map<String, dynamic> row) {
    final result = FoodSelection(
      FoodChoice.fromStorage(intakeMap(row['food'])),
      (row['amount'] as num).toDouble(),
      row['unit'] as String,
      estimated: row['estimated'] as bool? ?? false,
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
  });
  final String id;
  final int version;
  final DateTime eatenAt;
  final IntakeTotal total;
  final List<FoodSelection> items;
  final bool legacy;
  factory SavedIntake.fromJson(Map<String, dynamic> row) => SavedIntake(
    id: row['id'] as String,
    version: row['version'] as int,
    eatenAt: DateTime.parse(row['eaten_at'] as String).toUtc(),
    total: IntakeTotal.fromJson(intakeMap(row['total'])),
    legacy: row['legacy_snapshot_missing'] as bool,
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
    final food = FoodChoice(
      id: row['food_id'] as String,
      revision: row['revision_id'] as String,
      name: row['name'] as String,
      basisText: basis?['text'] as String?,
      basisUnit: basis?['unit'] as String?,
      servingReference: serving?['text'] as String?,
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
    );
  }
}

class IntakePage {
  const IntakePage(this.items, this.total, this.offset);
  final List<SavedIntake> items;
  final int total, offset;
}

class PendingIntake {
  const PendingIntake(this.owner, this.key, this.eatenAt, this.items);
  final String owner, key;
  final DateTime eatenAt;
  final List<FoodSelection> items;
  Map<String, dynamic> get body => {
    'eaten_at': eatenAt.toUtc().toIso8601String(),
    'items': items.map((item) => item.toJson()).toList(),
  };
  Map<String, dynamic> toStorage() => {
    'version': 1,
    'owner': owner,
    'key': key,
    'eaten_at': eatenAt.toUtc().toIso8601String(),
    'items': items.map((item) => item.toStorage()).toList(),
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
    );
    if (!RegExp(r'^[a-f0-9]{32}$').hasMatch(result.key) ||
        result.items.isEmpty ||
        result.items.length > 30) {
      throw const FormatException('Invalid pending request');
    }
    return result;
  }
}
