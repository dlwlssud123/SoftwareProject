import 'dart:async';
import 'package:flutter/material.dart';
import '../data/demo_repository.dart';
import '../models/recommendations.dart';
import '../models/recipe_ingredients.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/common.dart';

class RecommendationResults extends StatelessWidget {
  const RecommendationResults({
    required this.repository,
    required this.settings,
    required this.profile,
    required this.time,
    this.welfare = false,
    super.key,
  });
  final DemoRepository repository;
  final AppSettings settings;
  final UserProfile profile;
  final MealTime time;
  final bool welfare;

  @override
  Widget build(BuildContext context) {
    final meals = welfare
        ? <RecipeMatch>[]
        : repository.recommendMeals(profile, time);
    final services = welfare
        ? repository.recommendWelfare(profile)
        : <WelfareMatch>[];
    final count = welfare ? services.length : meals.length;
    return Scaffold(
      key: Key(welfare ? 'welfare-results' : 'recipe-results'),
      appBar: AppBar(title: Text(welfare ? '복지 추천 결과' : '식단 추천 결과')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(22, 10, 22, 28),
        children: [
          Row(
            children: [
              Tag(welfare ? '맞춤 복지 · 공공데이터' : '맞춤 식단 · 공공데이터'),
              const Spacer(),
              IconButton(
                tooltip: '추천 안내 읽어주기',
                onPressed: () => readAloud(
                  context,
                  settings,
                  '${profile.displayName}님을 위한 ${welfare ? '복지 서비스' : '레시피'} $count개를 찾았어요.',
                ),
                icon: const Icon(Icons.volume_up_outlined, color: green),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            '${profile.displayName}님을 위한\n${welfare ? '복지 서비스' : '${time.label} 레시피'}',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 7,
            runSpacing: 8,
            children: [
              Tag('${profile.age}세', color: muted),
              if (welfare) ...[
                Tag(profile.location, color: muted),
                Tag(profile.livesAlone ? '1인 가구' : '동거 가구', color: muted),
              ] else ...[
                for (final c in profile.conditions) Tag(c, color: muted),
                if (profile.softFood) const Tag('부드러운 음식', color: muted),
                if (profile.allergies.isNotEmpty)
                  Tag('${profile.allergies.join('·')} 제외', color: muted),
              ],
            ],
          ),
          SectionTitle(
            '추천 ${welfare ? '서비스' : '레시피'} $count개',
            trailing: TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('조건 수정'),
            ),
          ),
          if (count == 0) ...[
            const SizedBox(height: 25),
            const Icon(Icons.search_off_rounded, size: 56, color: muted),
            const SizedBox(height: 16),
            Text(
              welfare ? '관련 복지 정보를 찾지 못했어요.' : '조건에 맞는 레시피가 없어요.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 21, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 10),
            Text(
              welfare
                  ? '입력 정보를 확인하거나 복지로에서 다른 서비스를 찾아보세요.'
                  : '현재 저장된 레시피 ${repository.recipes.length}개에서 찾고 있어요.\n알레르기 조건은 유지하고 다른 조건을 확인해 주세요.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 20),
            OutlinedButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('추천 조건 다시 확인하기'),
            ),
          ],
          for (final match in meals)
            _RecipeCard(match: match, settings: settings),
          for (final match in services) _WelfareCard(match: match),
          const SizedBox(height: 12),
          Notice(
            welfare
                ? '입력 정보로 관련 제도를 정리했어요. 신청 자격은 각 서비스의 지원대상·선정기준과 담당 기관에서 확인해 주세요.'
                : '시간대와 건강 상태별로 정해 둔 예시 메뉴예요. 전문적인 식단 처방은 아니에요.',
          ),
          const SizedBox(height: 12),
          Text(
            welfare
                ? '출처: 복지로 중앙부처복지서비스 API\n전국 사업을 안내해요. 지역별 추가 사업은 포함하지 않아요.'
                : '출처: 식품안전나라 COOKRCP01 API\n알레르기 표기는 재료명 기반이며 원문도 확인해 주세요.',
            style: const TextStyle(fontSize: 13, height: 1.6, color: muted),
          ),
        ],
      ),
    );
  }
}

class _RecipeCard extends StatelessWidget {
  const _RecipeCard({required this.match, required this.settings});
  final RecipeMatch match;
  final AppSettings settings;
  @override
  Widget build(BuildContext context) {
    final r = match.recipe;
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Material(
        color: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: const BorderSide(color: line),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => RecipeDetail(recipe: r, settings: settings),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        ClipRRect(
                          borderRadius: BorderRadius.circular(16),
                          child: Image.asset(
                            r.image,
                            width: 92,
                            height: 106,
                            fit: BoxFit.cover,
                          ),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                r.name,
                                style: const TextStyle(
                                  fontSize: 20,
                                  fontWeight: FontWeight.w700,
                                  height: 1.45,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Tag(r.method),
                              const SizedBox(height: 8),
                              Text(
                                '${r.calories.toStringAsFixed(0)} kcal · 단백질 ${r.protein.toStringAsFixed(0)}g',
                                style: const TextStyle(
                                  fontSize: 14,
                                  color: muted,
                                  height: 1.5,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(
                          Icons.check_circle_outline_rounded,
                          color: green,
                          size: 19,
                        ),
                        const SizedBox(width: 7),
                        Expanded(
                          child: Text(
                            match.reasons.join(' · '),
                            style: const TextStyle(
                              fontSize: 14,
                              color: green,
                              height: 1.5,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    const Row(
                      children: [
                        Text(
                          '레시피 자세히 보기',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: green,
                          ),
                        ),
                        Spacer(),
                        Icon(
                          Icons.arrow_forward_rounded,
                          size: 19,
                          color: green,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WelfareCard extends StatelessWidget {
  const _WelfareCard({required this.match});
  final WelfareMatch match;
  @override
  Widget build(BuildContext context) {
    final service = match.service;
    final icon = switch (service.iconName) {
      'meal' => Icons.restaurant_rounded,
      'care' => Icons.favorite_border_rounded,
      'location' => Icons.location_on_outlined,
      'living' => Icons.account_balance_wallet_outlined,
      _ => Icons.local_florist_outlined,
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(21),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFFBECE2),
                  borderRadius: BorderRadius.circular(15),
                ),
                child: Icon(icon, color: const Color(0xFFB96543), size: 27),
              ),
              const SizedBox(width: 12),
              Tag(service.category),
              const Spacer(),
              Text(
                '${service.year}년',
                style: const TextStyle(fontSize: 13, color: muted),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Text(service.title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 10),
          Text(
            service.description,
            style: const TextStyle(fontSize: 16, height: 1.65, color: muted),
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: match.reasons.map(Tag.new).toList(),
          ),
          const SizedBox(height: 12),
          Material(
            color: Colors.white,
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: const EdgeInsets.only(bottom: 12),
              title: const Text('지원 대상과 혜택 보기', style: TextStyle(fontSize: 17)),
              children: [
                for (final section in [
                  ('지원 대상', service.targetDetails),
                  ('선정 기준', service.selectionCriteria),
                  ('지원 내용', service.benefits),
                ])
                  if (section.$2.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            section.$1,
                            style: const TextStyle(
                              fontSize: 17,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            section.$2,
                            style: const TextStyle(fontSize: 16, height: 1.6),
                          ),
                        ],
                      ),
                    ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => openLink(context, Uri.parse(service.sourceUrl)),
              icon: const Icon(Icons.open_in_new_rounded, size: 18),
              label: const Text('복지로 상세 보기'),
            ),
          ),
        ],
      ),
    );
  }
}

class RecipeDetail extends StatelessWidget {
  const RecipeDetail({required this.recipe, required this.settings, super.key});
  final Recipe recipe;
  final AppSettings settings;
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('레시피 살펴보기')),
    body: ListView(
      key: const Key('recipe-detail-scroll'),
      padding: const EdgeInsets.fromLTRB(22, 8, 22, 28),
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(24),
          child: Image.asset(
            recipe.image,
            height: 240,
            width: double.infinity,
            fit: BoxFit.cover,
          ),
        ),
        const SizedBox(height: 22),
        Text(recipe.name, style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            Tag(recipe.method),
            for (final allergen in recipe.allergens)
              Tag('$allergen 포함', color: const Color(0xFFAE652F)),
          ],
        ),
        const SectionTitle('영양 정보'),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            _Nutrient('열량', '${recipe.calories.toStringAsFixed(0)} kcal'),
            _Nutrient('단백질', '${recipe.protein.toStringAsFixed(0)} g'),
            _Nutrient('탄수화물', '${recipe.carbs.toStringAsFixed(0)} g'),
            _Nutrient('나트륨', '${recipe.sodium.toStringAsFixed(0)} mg'),
          ],
        ),
        const SizedBox(height: 10),
        const Text(
          '공공데이터 제공 수치 · 섭취량에 따라 달라져요.',
          style: TextStyle(fontSize: 13, color: muted),
        ),
        SectionTitle(
          '준비할 재료',
          trailing: IconButton(
            tooltip: '재료 읽어주기',
            onPressed: () => readAloud(context, settings, recipe.ingredients),
            icon: const Icon(Icons.volume_up_outlined, color: green),
          ),
        ),
        _IngredientList(source: recipe.ingredients),
        SectionTitle(
          '조리 방법',
          trailing: recipe.steps.isEmpty
              ? null
              : IconButton(
                  tooltip: '전체 조리 방법 읽어주기',
                  onPressed: () =>
                      readAloud(context, settings, recipe.steps.join('\n')),
                  icon: const Icon(Icons.volume_up_outlined, color: green),
                ),
        ),
        if (recipe.steps.isEmpty)
          const Notice('원본 데이터에 조리 방법이 제공되지 않았어요.')
        else ...[
          if (recipe.missingStepNumbers.isNotEmpty) ...[
            Notice(
              '원본 데이터에 ${recipe.missingStepNumbers.join('·')}단계가 없어 제공된 단계만 표시해요.',
            ),
            const SizedBox(height: 16),
          ],
          for (var i = 0; i < recipe.steps.length; i++)
            Padding(
              key: Key('recipe-step-$i'),
              padding: const EdgeInsets.only(bottom: 20),
              child: Text(
                recipe.steps[i],
                style: Theme.of(context).textTheme.bodyLarge,
              ),
            ),
        ],
        const SizedBox(height: 24),
        FilledButton.icon(
          onPressed: recipe.steps.isEmpty
              ? null
              : () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) =>
                        CookingScreen(recipe: recipe, settings: settings),
                  ),
                ),
          icon: const Icon(Icons.soup_kitchen_outlined),
          label: const Text('한 단계씩 따라 만들기'),
        ),
        const SizedBox(height: 20),
        TextButton.icon(
          onPressed: () => openLink(
            context,
            Uri.parse('https://www.foodsafetykorea.go.kr/'),
          ),
          icon: const Icon(Icons.open_in_new_rounded, size: 18),
          label: const Text('출처: 식품안전나라'),
        ),
      ],
    ),
  );
}

class _IngredientList extends StatelessWidget {
  const _IngredientList({required this.source});
  final String source;

  @override
  Widget build(BuildContext context) {
    final groups = parseRecipeIngredients(source);
    if (groups.isEmpty) {
      return const Notice('재료 정보가 제공되지 않았어요.');
    }
    return Column(
      key: const Key('recipe-ingredients'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var i = 0; i < groups.length; i++) ...[
          if (i > 0) const SizedBox(height: 20),
          if (groups[i].title != null) ...[
            Text(
              groups[i].title!,
              style: const TextStyle(
                fontSize: 19,
                fontWeight: FontWeight.w700,
                color: green,
                height: 1.5,
              ),
            ),
            const SizedBox(height: 8),
          ],
          Container(
            decoration: BoxDecoration(
              color: const Color(0xFFF5F8F6),
              border: Border.all(color: line),
              borderRadius: BorderRadius.circular(12),
            ),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (var j = 0; j < groups[i].items.length; j++) ...[
                  if (j > 0) const Divider(height: 1),
                  Padding(
                    key: Key('ingredient-$i-$j'),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    child: Wrap(
                      alignment: WrapAlignment.spaceBetween,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      spacing: 16,
                      runSpacing: 6,
                      children: [
                        Text(
                          groups[i].items[j].name,
                          style: const TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            height: 1.5,
                          ),
                        ),
                        if (groups[i].items[j].quantity != null)
                          Text(
                            groups[i].items[j].quantity!,
                            style: const TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.w600,
                              color: green,
                              height: 1.5,
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ],
    );
  }
}

class _Nutrient extends StatelessWidget {
  const _Nutrient(this.label, this.value);
  final String label, value;
  @override
  Widget build(BuildContext context) => Container(
    width: (MediaQuery.sizeOf(context).width - 54) / 2,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(16),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 14, color: muted)),
        const SizedBox(height: 7),
        Text(
          value,
          style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
        ),
      ],
    ),
  );
}

class CookingScreen extends StatefulWidget {
  const CookingScreen({
    required this.recipe,
    required this.settings,
    super.key,
  });
  final Recipe recipe;
  final AppSettings settings;
  @override
  State<CookingScreen> createState() => _CookingScreenState();
}

class _CookingScreenState extends State<CookingScreen> {
  int step = 0, remaining = 0;
  Timer? timer;
  void startTimer() {
    timer?.cancel();
    setState(() => remaining = 60);
    timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      setState(() => remaining--);
      if (remaining == 0) {
        t.cancel();
        showMessage(context, '1분이 지났어요.');
        if (widget.settings.voice) {
          readAloud(context, widget.settings, '1분이 지났어요.');
        }
      }
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    widget.settings.stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('천천히 따라 만들어요')),
    body: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text(
          widget.recipe.name,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 24),
        Tag('제공된 단계 ${step + 1} / ${widget.recipe.steps.length}'),
        const SizedBox(height: 25),
        Text(
          widget.recipe.steps[step],
          style: const TextStyle(
            fontSize: 26,
            height: 1.8,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 32),
        OutlinedButton.icon(
          onPressed: () =>
              readAloud(context, widget.settings, widget.recipe.steps[step]),
          icon: const Icon(Icons.volume_up_outlined),
          label: const Text('이 단계 읽어주기'),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: remaining > 0
              ? () {
                  timer?.cancel();
                  setState(() => remaining = 0);
                }
              : startTimer,
          icon: const Icon(Icons.timer_outlined),
          label: Text(remaining > 0 ? '$remaining초 남음 · 타이머 취소' : '1분 타이머 시작'),
        ),
        const SizedBox(height: 30),
        Row(
          children: [
            if (step > 0) ...[
              Expanded(
                child: OutlinedButton(
                  onPressed: () {
                    widget.settings.stop();
                    setState(() => step--);
                  },
                  child: const Text('이전 단계'),
                ),
              ),
              const SizedBox(width: 12),
            ],
            Expanded(
              child: FilledButton(
                onPressed: () {
                  if (step == widget.recipe.steps.length - 1) {
                    Navigator.of(context).pop();
                  } else {
                    widget.settings.stop();
                    setState(() => step++);
                  }
                },
                child: Text(
                  step == widget.recipe.steps.length - 1 ? '조리 마치기' : '다음 단계',
                ),
              ),
            ),
          ],
        ),
      ],
    ),
  );
}
