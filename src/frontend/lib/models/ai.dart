import 'intake.dart';

class PhotoMatch {
  const PhotoMatch(
    this.food,
    this.amount,
    this.unit,
    this.description, {
    this.isSimilar = false,
    this.nutrients,
  });
  final FoodChoice food;
  final double amount;
  final String unit, description;
  final bool isSimilar;
  final IntakeNutrients? nutrients;

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
    );
  }

  FoodSelection portion(double factor) =>
      FoodSelection(food, amount * factor, unit, estimated: true);
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
