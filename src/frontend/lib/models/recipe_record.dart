/// 서버 레시피 응답(`RecipeRecord`)을 앱에서 쓰는 모델.
///
/// 계약: docs/설계/API_명세서.md 9·10절, catalog.openapi.json의 RecipeRecord.
/// - 누락된 영양값은 0으로 채우지 않고 null로 둔다.
/// - 원천 ID는 숫자처럼 보여도 문자열로 유지한다.
class RecipeRecord {
  const RecipeRecord({
    required this.recipeId,
    required this.name,
    required this.category,
    required this.cookingMethod,
    required this.imageSmall,
    required this.imageLarge,
    required this.ingredientsText,
    required this.ingredients,
    required this.steps,
    required this.missingStepNos,
    required this.nutrition,
    required this.sodiumTip,
    required this.allergens,
    required this.qualityStatus,
  });

  final String recipeId;
  final String name;
  final String? category;
  final String? cookingMethod;
  final String? imageSmall;
  final String? imageLarge;
  final String? ingredientsText;
  final List<RecipeIngredientItem> ingredients;
  final List<RecipeStepItem> steps;
  final List<int> missingStepNos;
  final RecipeNutritionInfo nutrition;
  final String? sodiumTip;
  final RecipeAllergenInfo allergens;
  final String qualityStatus;

  factory RecipeRecord.fromJson(Map<String, dynamic> json) {
    final images = json['images'] as Map<String, dynamic>;
    final quality = json['quality'] as Map<String, dynamic>;
    return RecipeRecord(
      recipeId: json['recipe_id'] as String,
      name: json['name'] as String,
      category: json['category'] as String?,
      cookingMethod: json['cooking_method'] as String?,
      imageSmall: images['small'] as String?,
      imageLarge: images['large'] as String?,
      ingredientsText: json['ingredients_text'] as String?,
      ingredients: [
        for (final row in json['ingredients'] as List)
          RecipeIngredientItem.fromJson(row as Map<String, dynamic>),
      ],
      steps: [
        for (final row in json['steps'] as List)
          RecipeStepItem.fromJson(row as Map<String, dynamic>),
      ],
      missingStepNos: [
        for (final no in json['missing_step_nos'] as List) no as int,
      ],
      nutrition: RecipeNutritionInfo.fromJson(
        json['nutrition'] as Map<String, dynamic>,
      ),
      sodiumTip: json['sodium_tip'] as String?,
      allergens: RecipeAllergenInfo.fromJson(
        json['allergens'] as Map<String, dynamic>,
      ),
      qualityStatus: quality['status'] as String,
    );
  }
}

class RecipeIngredientItem {
  const RecipeIngredientItem({
    required this.orderNo,
    required this.section,
    required this.name,
    required this.amountText,
  });

  final int orderNo;
  final String? section;
  final String name;
  final String? amountText;

  factory RecipeIngredientItem.fromJson(Map<String, dynamic> json) =>
      RecipeIngredientItem(
        orderNo: json['order_no'] as int,
        section: json['section'] as String?,
        name: json['name'] as String,
        amountText: json['amount_text'] as String?,
      );
}

class RecipeStepItem {
  const RecipeStepItem({
    required this.no,
    required this.text,
    required this.image,
  });

  final int no;
  final String text;
  final String? image;

  factory RecipeStepItem.fromJson(Map<String, dynamic> json) => RecipeStepItem(
    no: json['no'] as int,
    text: json['text'] as String,
    image: json['image'] as String?,
  );
}

/// 1인분 기준으로 확인되지 않은 영양값(`basis=per_serving_unverified`).
/// 화면에서는 참고값으로만 표시하고, 값이 없으면 '정보 없음'으로 보여준다.
class RecipeNutritionInfo {
  const RecipeNutritionInfo({
    required this.energyKcal,
    required this.carbohydrateG,
    required this.proteinG,
    required this.fatG,
    required this.sodiumMg,
    required this.suspect,
  });

  final double? energyKcal;
  final double? carbohydrateG;
  final double? proteinG;
  final double? fatG;
  final double? sodiumMg;

  /// 열량과 3대 영양소 계산이 크게 어긋나 의심되는 값인지.
  final bool suspect;

  factory RecipeNutritionInfo.fromJson(Map<String, dynamic> json) =>
      RecipeNutritionInfo(
        energyKcal: _number(json['energy_kcal']),
        carbohydrateG: _number(json['carbohydrate_g']),
        proteinG: _number(json['protein_g']),
        fatG: _number(json['fat_g']),
        sodiumMg: _number(json['sodium_mg']),
        suspect: json['suspect'] as bool,
      );

  static double? _number(Object? value) =>
      value is num ? value.toDouble() : null;
}

/// 재료 이름 기준 알레르기 판정 결과. 이름은 서버 표기(예: 알류)다.
class RecipeAllergenInfo {
  const RecipeAllergenInfo({
    required this.detected,
    required this.needsCheck,
    required this.notDeterminable,
    required this.complete,
  });

  final Set<String> detected;

  /// 재료 이름만으로 확정할 수 없어 확인이 필요한 후보.
  final Set<String> needsCheck;

  /// 원재료명으로는 판단할 수 없는 항목.
  final Set<String> notDeterminable;

  /// false면 알레르기 분석이 끝나지 않은 것이므로 안전 확인 완료로 표시하지 않는다.
  final bool complete;

  /// 알레르기 제외 시 피해야 하는 항목: 검출 + 확인 필요 후보(명세서 9절).
  Set<String> get toAvoid => {...detected, ...needsCheck};

  factory RecipeAllergenInfo.fromJson(Map<String, dynamic> json) =>
      RecipeAllergenInfo(
        detected: {
          for (final row in json['detected'] as List)
            (row as Map<String, dynamic>)['allergen'] as String,
        },
        needsCheck: {
          for (final row in json['needs_check'] as List)
            for (final name
                in (row as Map<String, dynamic>)['candidates'] as List)
              name as String,
        },
        notDeterminable: {
          for (final name in json['not_determinable'] as List) name as String,
        },
        complete: json['complete'] as bool,
      );
}

/// 앱 화면 표기 → 서버 표기. 앱의 '달걀'은 서버에서 '알류'다.
String serverAllergenName(String appName) => appName == '달걀' ? '알류' : appName;

/// 서버 표기 → 앱 화면 표기.
String appAllergenName(String serverName) =>
    serverName == '알류' ? '달걀' : serverName;
