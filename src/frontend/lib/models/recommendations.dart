enum MealTime {
  breakfast('아침', '가볍고 든든하게'),
  lunch('점심', '균형 있게 한 끼'),
  dinner('저녁', '편안하게 마무리'),
  snack('간식', '출출할 때 조금');

  const MealTime(this.label, this.description);
  final String label, description;
}

class UserProfile {
  const UserProfile({
    required this.name,
    required this.age,
    required this.gender,
    required this.region,
    required this.district,
    this.livesAlone = true,
    this.income = '선택 안 함',
    this.conditions = const {},
    this.allergies = const {},
    this.softFood = false,
  });
  final String name, gender, region, district, income;
  final int age;
  final bool livesAlone, softFood;
  final Set<String> conditions, allergies;
  String get displayName => name.trim().isEmpty ? '어르신' : name.trim();
  String get location => '$region $district';
}

class Recipe {
  const Recipe({
    required this.id,
    required this.name,
    required this.ingredients,
    required this.steps,
    required this.calories,
    required this.sodium,
    required this.protein,
    required this.carbs,
    required this.fat,
    required this.method,
    required this.allergens,
    required this.soft,
  });
  final String id, name, ingredients, method;
  final List<String> steps;
  final double calories, sodium, protein, carbs, fat;
  final Set<String> allergens;
  final bool soft;
  String get image => 'assets/images/$id.png';

  List<int> get missingStepNumbers {
    final numbers = <int>{};
    for (final text in steps) {
      final match = RegExp(r'^\s*(\d+)\s*[.)]').firstMatch(text);
      if (match != null) numbers.add(int.parse(match.group(1)!));
    }
    if (numbers.isEmpty) return const [];
    final last = numbers.reduce((a, b) => a > b ? a : b);
    return [
      for (var i = 1; i < last; i++)
        if (!numbers.contains(i)) i,
    ];
  }

  factory Recipe.fromPublicData(Map<String, dynamic> json) {
    final ingredients = json['RCP_PARTS_DTLS'] as String;
    final allergens = <String>{};
    const terms = {
      '달걀': ['달걀', '계란'],
      '우유': ['우유', '생크림', '버터', '치즈'],
      '대두': ['두부', '콩', '된장', '간장'],
      '새우': ['새우'],
      '밀': ['밀가루', '간장'],
      '땅콩': ['땅콩'],
    };
    for (final entry in terms.entries) {
      if (entry.value.any(ingredients.contains)) allergens.add(entry.key);
    }
    double number(String key) => double.tryParse('${json[key]}') ?? 0;
    return Recipe(
      id: json['RCP_SEQ'] as String,
      name: json['RCP_NM'] as String,
      ingredients: ingredients,
      steps: [
        for (var i = 1; i <= 20; i++)
          if ('${json['MANUAL${i.toString().padLeft(2, '0')}'] ?? ''}'
              .trim()
              .isNotEmpty)
            '${json['MANUAL${i.toString().padLeft(2, '0')}']}'
                .replaceAll(RegExp(r'[a-z]$'), '')
                .trim(),
      ],
      calories: number('INFO_ENG'),
      sodium: number('INFO_NA'),
      protein: number('INFO_PRO'),
      carbs: number('INFO_CAR'),
      fat: number('INFO_FAT'),
      method: json['RCP_WAY2'] as String,
      allergens: allergens,
      soft: ['28', '33'].contains(json['RCP_SEQ']),
    );
  }
}

class RecipeMatch {
  const RecipeMatch(this.recipe, this.reasons);
  final Recipe recipe;
  final List<String> reasons;
}

class WelfareService {
  const WelfareService({
    required this.id,
    required this.title,
    required this.description,
    required this.category,
    required this.iconName,
    required this.sourceUrl,
    required this.targetDetails,
    required this.selectionCriteria,
    required this.benefits,
    required this.householdTypes,
    required this.year,
  });
  final String id, title, description, category, iconName;
  final String sourceUrl, targetDetails, selectionCriteria, benefits, year;
  final List<String> householdTypes;

  factory WelfareService.fromPublicData(Map<String, dynamic> json) {
    final id = json['servId'] as String;
    return WelfareService(
      id: id,
      title: json['servNm'] as String,
      description: json['servDgst'] as String,
      category: (json['intrsThemaArray'] as String).split(',').first,
      iconName: switch (id) {
        'WLF00003191' || 'WLF00001093' => 'care',
        'WLF00001164' || 'WLF00000072' => 'living',
        _ => 'culture',
      },
      sourceUrl: json['servDtlLink'] as String,
      targetDetails: json['tgtrDtlCn'] as String,
      selectionCriteria: json['slctCritCn'] as String,
      benefits: json['alwServCn'] as String,
      householdTypes: (json['trgterIndvdlArray'] as String? ?? '').split(','),
      year: json['crtrYr'] as String,
    );
  }
}

class WelfareMatch {
  const WelfareMatch(this.service, this.reasons);
  final WelfareService service;
  final List<String> reasons;
}
