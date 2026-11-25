import 'intake.dart';

class PhotoMatch {
  const PhotoMatch(
    this.food,
    this.amount,
    this.unit,
    this.description, {
    this.isSimilar = false,
    this.nutrients,
    this.quantityBasis = 'ai_estimate',
    this.manuallySelected = false,
  });
  final FoodChoice food;
  final double amount;
  final String unit, description;
  final bool isSimilar;
  final IntakeNutrients? nutrients;
  final String quantityBasis;
  final bool manuallySelected;

  factory PhotoMatch.fromJson(Map<String, dynamic> row) {
    final serving = intakeMap(row['serving']);
    final amount = (serving['amount'] as num).toDouble();
    final unit = serving['unit'] as String;
    final nutrition = intakeMap(row['food'])['nutrients'];
    if (!amount.isFinite ||
        amount <= 0 ||
        amount > 10000 ||
        !{'g', 'mL'}.contains(unit)) {
      throw const FormatException('Invalid serving suggestion');
    }
    return PhotoMatch(
      FoodChoice.fromJson(intakeMap(row['food'])),
      amount,
      unit,
      serving['description'] as String,
      isSimilar: row['match_basis'] == 'similar',
      nutrients: nutrition is Map<String, dynamic>
          ? IntakeNutrients.fromJson(nutrition)
          : null,
      quantityBasis: serving['basis'] == 'source_serving'
          ? 'source_serving'
          : 'ai_estimate',
    );
  }

  FoodSelection portion(
    double factor, {
    String? recognizedName,
    FoodOrigin? origin,
  }) => FoodSelection(
    food,
    amount * factor,
    unit,
    estimated: true,
    origin:
        origin ??
        (recognizedName == null
            ? null
            : FoodOrigin(
                method: manuallySelected
                    ? 'manual'
                    : isSimilar
                    ? 'similar_food'
                    : 'photo',
                recognizedName: recognizedName,
                quantityBasis: factor == 1 ? quantityBasis : 'user_adjusted',
              )),
  );
}

class PhotoDish {
  const PhotoDish(this.name, this.confidence, this.grams, this.matches);
  final String name, confidence;
  final int grams;
  final List<PhotoMatch> matches;
  factory PhotoDish.fromJson(Map<String, dynamic> row) => PhotoDish(
    row['name'] as String,
    row['confidence'] as String,
    row['standard_serving_grams'] as int,
    [
      for (final match in row['matches'] as List)
        PhotoMatch.fromJson(intakeMap(match)),
    ],
  );
}

class PhotoRecognition {
  const PhotoRecognition(this.foods, this.notice);
  final List<PhotoDish> foods;
  final String notice;
  factory PhotoRecognition.fromJson(Map<String, dynamic> row) =>
      PhotoRecognition([
        for (final dish in row['foods'] as List)
          PhotoDish.fromJson(intakeMap(dish)),
      ], row['notice'] as String);
}

class IngredientGuess {
  const IngredientGuess(
    this.name,
    this.grams,
    this.matches, {
    this.isWater = false,
  });
  final String name;
  final double grams;
  final List<PhotoMatch> matches;
  final bool isWater;
  factory IngredientGuess.fromJson(Map<String, dynamic> row) {
    final grams = (row['amount_g'] as num).toDouble();
    if (!grams.isFinite || grams <= 0 || grams > 1500) {
      throw const FormatException('Invalid ingredient amount');
    }
    return IngredientGuess(row['name'] as String, grams, [
      for (final match in row['matches'] as List)
        PhotoMatch.fromJson(intakeMap(match)),
    ], isWater: row['is_water'] == true);
  }
}

class IngredientEstimate {
  const IngredientEstimate(this.ingredients, this.notice, {this.referenceName});
  final List<IngredientGuess> ingredients;
  final String notice;
  final String? referenceName;
  factory IngredientEstimate.fromJson(Map<String, dynamic> row) {
    final items = [
      for (final item in row['ingredients'] as List)
        IngredientGuess.fromJson(intakeMap(item)),
    ];
    if (items.isEmpty || items.length > 8) {
      throw const FormatException('Invalid ingredient list');
    }
    return IngredientEstimate(
      items,
      row['notice'] as String,
      referenceName: row['reference_recipe'] == null
          ? null
          : intakeMap(row['reference_recipe'])['name'] as String,
    );
  }
}
