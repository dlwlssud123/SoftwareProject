import 'dart:convert';
import 'package:flutter/services.dart';
import '../models/recommendations.dart';

class DemoRepository {
  const DemoRepository(this.recipes, this.welfareServices);
  final List<Recipe> recipes;
  final List<WelfareService> welfareServices;
  static Future<DemoRepository> load() async {
    final raw =
        jsonDecode(await rootBundle.loadString('assets/data/recipes.json'))
            as List;
    final welfareRaw =
        jsonDecode(
              await rootBundle.loadString('assets/data/welfare_services.json'),
            )
            as List;
    return DemoRepository(
      raw
          .map((row) => Recipe.fromPublicData(row as Map<String, dynamic>))
          .toList(),
      welfareRaw
          .map(
            (row) => WelfareService.fromPublicData(row as Map<String, dynamic>),
          )
          .toList(),
    );
  }

  // Fixed presentation scenarios; the order is not a clinical diet assessment.
  static const _mealOrders = {
    MealTime.breakfast: {
      '기본': ['28', '33', '29', '32', '31'],
      '고혈압': ['33', '28', '32', '29', '31'],
      '당뇨': ['28', '33', '31', '32', '29'],
      '고혈압·당뇨': ['33', '28', '32', '31', '29'],
    },
    MealTime.lunch: {
      '기본': ['29', '28', '33', '32', '31'],
      '고혈압': ['32', '28', '33', '29', '31'],
      '당뇨': ['33', '28', '31', '32', '29'],
      '고혈압·당뇨': ['33', '32', '28', '31', '29'],
    },
    MealTime.dinner: {
      '기본': ['33', '28', '29', '32', '31'],
      '고혈압': ['32', '33', '28', '29', '31'],
      '당뇨': ['33', '28', '32', '31', '29'],
      '고혈압·당뇨': ['33', '28', '32', '31', '29'],
    },
    MealTime.snack: {
      '기본': ['31', '32', '33', '28', '29'],
      '고혈압': ['32', '33', '28', '29', '31'],
      '당뇨': ['31', '33', '28', '32', '29'],
      '고혈압·당뇨': ['32', '33', '28', '31', '29'],
    },
  };

  List<RecipeMatch> recommendMeals(UserProfile profile, MealTime time) {
    final hypertension = profile.conditions.contains('고혈압');
    final diabetes = profile.conditions.contains('당뇨');
    var scenario = '기본';
    if (hypertension && diabetes) {
      scenario = '고혈압·당뇨';
    } else if (hypertension) {
      scenario = '고혈압';
    } else if (diabetes) {
      scenario = '당뇨';
    }
    final order = _mealOrders[time]![scenario]!;
    final candidates = recipes.where((recipe) {
      if (recipe.allergens.intersection(profile.allergies).isNotEmpty) {
        return false;
      }
      if (profile.softFood && !recipe.soft) return false;
      return true;
    }).toList();
    int priority(Recipe recipe) {
      final index = order.indexOf(recipe.id);
      return index < 0 ? order.length : index;
    }

    candidates.sort((a, b) {
      final comparison = priority(a).compareTo(priority(b));
      return comparison == 0 ? a.id.compareTo(b.id) : comparison;
    });
    return candidates
        .take(5)
        .map(
          (recipe) => RecipeMatch(recipe, [
            if (profile.allergies.isNotEmpty) '선택한 알레르기 재료 제외',
            if (profile.softFood) '부드러운 조리 방식 우선',
            if (hypertension) '고혈압 선택을 반영한 예시 추천',
            if (diabetes) '당뇨 선택을 반영한 예시 추천',
            '${time.label} 시간대에 맞춘 예시 메뉴',
          ]),
        )
        .toList();
  }

  // Age gates select the senior-facing information, not benefit eligibility.
  static const _welfareMinAges = {
    'WLF00003191': 65,
    'WLF00001093': 65,
    'WLF00001164': 65,
    'WLF00001155': 60,
    'WLF00000072': 65,
    'WLF00000055': 6,
  };
  static const _careServiceIds = {'WLF00003191', 'WLF00001093'};
  static const _incomeSupportIds = {
    'WLF00001164',
    'WLF00000072',
    'WLF00000055',
  };

  List<WelfareMatch> recommendWelfare(UserProfile profile) {
    final lowIncome = profile.income == '중위소득 50% 이하';
    final candidates = welfareServices
        .where((service) => profile.age >= (_welfareMinAges[service.id] ?? 0))
        .toList();
    int priority(WelfareService service) {
      var score = 0;
      if (profile.livesAlone && _careServiceIds.contains(service.id)) {
        score += 30;
      }
      if (lowIncome && _incomeSupportIds.contains(service.id)) score += 20;
      return score;
    }

    candidates.sort((a, b) {
      final comparison = priority(b).compareTo(priority(a));
      return comparison == 0 ? a.id.compareTo(b.id) : comparison;
    });
    return candidates
        .map(
          (service) => WelfareMatch(service, [
            '입력 나이 ${profile.age}세를 고려',
            if (profile.livesAlone && _careServiceIds.contains(service.id))
              '혼자 사는 생활을 고려',
            if (lowIncome && service.householdTypes.contains('저소득'))
              '선택한 소득 구간을 고려',
            if (service.householdTypes.contains('저소득')) '실제 소득 기준 확인 필요',
          ]),
        )
        .toList();
  }
}
