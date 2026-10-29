import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/models/recommendations.dart';

UserProfile profile({
  Set<String> allergies = const {},
  Set<String> conditions = const {},
  bool soft = false,
  int age = 72,
  bool alone = true,
  String region = '서울특별시',
  String income = '중위소득 50% 이하',
}) => UserProfile(
  name: '테스트',
  age: age,
  gender: '여성',
  region: region,
  district: '예시구',
  livesAlone: alone,
  income: income,
  allergies: allergies,
  conditions: conditions,
  softFood: soft,
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late DemoRepository repository;
  setUpAll(() async => repository = await DemoRepository.load());

  test('public recipe source retains usable images and cooking steps', () {
    expect(repository.recipes, hasLength(50));
    expect(
      repository.recipes.every((r) => r.steps.isNotEmpty && r.calories > 0),
      isTrue,
    );
    expect(
      repository.recipes.singleWhere((r) => r.id == '28').allergens,
      containsAll(['달걀', '우유', '대두', '새우']),
    );
  });

  test('sparse cooking steps retain original numbers through MANUAL20', () {
    final recipe = Recipe.fromPublicData({
      'RCP_SEQ': '28',
      'RCP_NM': '단계 확인',
      'RCP_PARTS_DTLS': '재료',
      'RCP_WAY2': '찌기',
      'MANUAL01': '1. 재료를 준비한다.',
      'MANUAL02': '   ',
      'MANUAL03': '3. 재료를 익힌다.',
      'MANUAL20': '20. 접시에 담는다.',
    });
    expect(recipe.steps, ['1. 재료를 준비한다.', '3. 재료를 익힌다.', '20. 접시에 담는다.']);
    expect(recipe.missingStepNumbers, [2, for (var i = 4; i < 20; i++) i]);
    expect(
      repository.recipes.singleWhere((r) => r.id == '33').missingStepNumbers,
      [1, 4],
    );
    expect(
      repository.recipes.singleWhere((r) => r.id == '32').missingStepNumbers,
      isEmpty,
    );
  });

  test('allergy exclusions are applied before any ranking', () {
    final matches = repository.recommendMeals(
      profile(allergies: {'새우', '대두'}),
      MealTime.lunch,
    );
    expect(matches, isNotEmpty);
    expect(
      matches.every(
        (m) => m.recipe.allergens.intersection({'새우', '대두'}).isEmpty,
      ),
      isTrue,
    );
    expect(
      matches.any((m) => m.recipe.id == '28' || m.recipe.id == '33'),
      isFalse,
    );
  });

  test(
    'impossible restrictions produce no results instead of unsafe fallbacks',
    () {
      expect(
        repository.recommendMeals(
          profile(allergies: {'새우'}, soft: true),
          MealTime.dinner,
        ),
        isEmpty,
      );
    },
  );

  test('health choice selects its fixed presentation scenario', () {
    final matches = repository.recommendMeals(
      profile(conditions: {'고혈압'}),
      MealTime.dinner,
    );
    expect(matches.first.recipe.id, '32');
    expect(matches.first.reasons, contains('고혈압 선택을 반영한 예시 추천'));
  });

  test('each meal time has a distinct default first recommendation', () {
    final firstIds = [
      for (final time in MealTime.values)
        repository.recommendMeals(profile(), time).first.recipe.id,
    ];
    expect(firstIds, ['28', '29', '33', '31']);
  });

  test('lunch changes for default, hypertension, diabetes and both', () {
    List<String> ids(Set<String> conditions) => repository
        .recommendMeals(profile(conditions: conditions), MealTime.lunch)
        .map((m) => m.recipe.id)
        .toList();
    expect(ids({}), ['29', '28', '33', '32', '31']);
    expect(ids({'고혈압'}), ['32', '28', '33', '29', '31']);
    expect(ids({'당뇨'}), ['33', '28', '31', '32', '29']);
    expect(ids({'고혈압', '당뇨'}), ['33', '32', '28', '31', '29']);
  });

  test('every scenario preserves exclusions and returns unique sample IDs', () {
    for (final time in MealTime.values) {
      for (final conditions in [
        <String>{},
        {'고혈압'},
        {'당뇨'},
        {'고혈압', '당뇨'},
      ]) {
        final matches = repository.recommendMeals(
          profile(conditions: conditions, allergies: {'새우'}),
          time,
        );
        final ids = matches.map((m) => m.recipe.id).toSet();
        expect(ids, containsAll({'29', '31', '32'}));
        expect(ids.length, matches.length);
        expect(matches, hasLength(5));
        expect(
          matches.every((m) => !m.recipe.allergens.contains('새우')),
          isTrue,
        );
        expect(
          repository.recommendMeals(
            profile(conditions: conditions, allergies: {'새우'}, soft: true),
            time,
          ),
          isEmpty,
        );
      }
    }
  });

  test('soft-food choice only returns the curated soft recipes', () {
    final matches = repository.recommendMeals(
      profile(soft: true),
      MealTime.breakfast,
    );
    expect(matches, hasLength(2));
    expect(matches.every((m) => m.recipe.soft), isTrue);
  });

  test(
    'welfare services contain actual API IDs, details and official links',
    () {
      expect(repository.welfareServices, hasLength(6));
      for (final service in repository.welfareServices) {
        expect(service.id, startsWith('WLF'));
        expect(service.targetDetails, isNotEmpty);
        expect(service.benefits, isNotEmpty);
        expect(Uri.parse(service.sourceUrl).host, 'www.bokjiro.go.kr');
        expect(
          Uri.parse(service.sourceUrl).queryParameters['wlfareInfoId'],
          service.id,
        );
      }
    },
  );

  test(
    'central welfare services apply nationwide without invented local items',
    () {
      final seoul = repository
          .recommendWelfare(profile())
          .map((m) => m.service.id)
          .toSet();
      expect(seoul, containsAll(['WLF00003191', 'WLF00001093', 'WLF00001164']));
      final busan = repository
          .recommendWelfare(profile(region: '부산광역시'))
          .map((m) => m.service.id)
          .toSet();
      expect(busan, seoul);
    },
  );

  test('age selects relevant senior-facing information', () {
    final young = repository.recommendWelfare(
      profile(age: 45, alone: false, income: '선택 안 함'),
    );
    expect(young.map((m) => m.service.id), ['WLF00000055']);
    final sixty = repository.recommendWelfare(profile(age: 60));
    expect(sixty.map((m) => m.service.id).toSet(), {
      'WLF00000055',
      'WLF00001155',
    });
  });

  test(
    'household and income prioritize relevant services without granting eligibility',
    () {
      final alone = repository.recommendWelfare(profile());
      expect(alone.take(2).map((m) => m.service.id).toSet(), {
        'WLF00003191',
        'WLF00001093',
      });
      final lowIncome = repository.recommendWelfare(profile(alone: false));
      final lowIds = lowIncome.map((m) => m.service.id).toList();
      expect(
        lowIds.indexOf('WLF00001164'),
        lessThan(lowIds.indexOf('WLF00001155')),
      );
      final unknown = repository.recommendWelfare(
        profile(alone: false, income: '잘 모르겠어요'),
      );
      final unknownIds = unknown.map((m) => m.service.id).toList();
      expect(
        unknownIds.indexOf('WLF00001155'),
        lessThan(unknownIds.indexOf('WLF00001164')),
      );
      expect(
        unknown.every((m) => !m.reasons.contains('선택한 소득 구간을 고려')),
        isTrue,
      );
      expect(
        unknown.every((m) => m.reasons.contains('실제 소득 기준 확인 필요')),
        isTrue,
      );
    },
  );
}
