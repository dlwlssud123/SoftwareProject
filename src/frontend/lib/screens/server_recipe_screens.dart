import 'package:flutter/material.dart';

import '../core/network/api_exception.dart';
import '../data/recipe_api.dart';
import '../models/recipe_record.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/async_state_view.dart';
import '../widgets/common.dart';

const _recipeColor = Color(0xFFB85A00);

/// 서버 레시피 목록(`GET /api/v1/recipes`). 서버 주소가 있을 때만 열린다.
class ServerRecipeList extends StatefulWidget {
  const ServerRecipeList({
    required this.api,
    required this.settings,
    super.key,
  });

  final RecipeApi api;
  final AppSettings settings;

  @override
  State<ServerRecipeList> createState() => _ServerRecipeListState();
}

class _ServerRecipeListState extends State<ServerRecipeList> {
  static const _pageSize = 20;

  final _items = <RecipeRecord>[];
  int _total = 0;
  bool _loading = true;
  bool _loadingMore = false;
  ApiException? _error;

  @override
  void initState() {
    super.initState();
    _loadFirstPage();
  }

  Future<void> _loadFirstPage() async {
    try {
      final page = await widget.api.list(limit: _pageSize);
      if (!mounted) return;
      setState(() {
        _items
          ..clear()
          ..addAll(page.items);
        _total = page.total;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error;
        _loading = false;
      });
    }
  }

  void _retry() {
    setState(() {
      _loading = true;
      _error = null;
    });
    _loadFirstPage();
  }

  Future<void> _loadMore() async {
    if (_loadingMore) return;
    setState(() => _loadingMore = true);
    try {
      final page = await widget.api.list(
        limit: _pageSize,
        offset: _items.length,
      );
      if (!mounted) return;
      setState(() {
        _items.addAll(page.items);
        _total = page.total;
      });
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.message);
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    key: const Key('server-recipe-list'),
    appBar: AppBar(title: const Text('레시피 살펴보기')),
    body: AsyncStateView(
      loading: _loading,
      error: _error,
      onRetry: _retry,
      isEmpty: _items.isEmpty,
      loadingMessage: '레시피를 불러오는 중이에요',
      emptyMessage: '보여드릴 레시피가 없어요',
      builder: (context) => ListView(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 24),
        children: [
          Text(
            '레시피 $_total개',
            style: const TextStyle(fontSize: 15, color: muted),
          ),
          const SizedBox(height: 10),
          for (final recipe in _items)
            FeatureTile(
              key: Key('server-recipe-${recipe.recipeId}'),
              title: recipe.name,
              subtitle: _summary(recipe),
              icon: Icons.menu_book_outlined,
              color: _recipeColor,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => ServerRecipeDetail(
                    api: widget.api,
                    recipeId: recipe.recipeId,
                    settings: widget.settings,
                  ),
                ),
              ),
            ),
          if (_items.length < _total)
            OutlinedButton(
              key: const Key('server-recipe-more'),
              onPressed: _loadingMore ? null : _loadMore,
              child: Text(_loadingMore ? '불러오는 중이에요' : '레시피 더 보기'),
            ),
          const SizedBox(height: 12),
          const Text(
            '출처: 식품안전나라 COOKRCP01\n영양 수치는 1인분 기준이 확인되지 않은 참고값이에요.',
            style: TextStyle(fontSize: 13, color: muted, height: 1.6),
          ),
        ],
      ),
    ),
  );

  static String _summary(RecipeRecord recipe) => [
    ?recipe.category,
    ?recipe.cookingMethod,
    _amount('열량', recipe.nutrition.energyKcal, 'kcal'),
  ].join(' · ');
}

/// 서버 레시피 상세(`GET /api/v1/recipes/{id}`).
class ServerRecipeDetail extends StatefulWidget {
  const ServerRecipeDetail({
    required this.api,
    required this.recipeId,
    required this.settings,
    super.key,
  });

  final RecipeApi api;
  final String recipeId;
  final AppSettings settings;

  @override
  State<ServerRecipeDetail> createState() => _ServerRecipeDetailState();
}

class _ServerRecipeDetailState extends State<ServerRecipeDetail> {
  RecipeRecord? _recipe;
  bool _loading = true;
  ApiException? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final recipe = await widget.api.detail(widget.recipeId);
      if (!mounted) return;
      setState(() {
        _recipe = recipe;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error;
        _loading = false;
      });
    }
  }

  void _retry() {
    setState(() {
      _loading = true;
      _error = null;
    });
    _load();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('레시피 살펴보기')),
    body: AsyncStateView(
      loading: _loading,
      error: _error,
      onRetry: _retry,
      isEmpty: false,
      loadingMessage: '레시피를 불러오는 중이에요',
      builder: (context) =>
          _RecipeBody(recipe: _recipe!, settings: widget.settings),
    ),
  );
}

class _RecipeBody extends StatelessWidget {
  const _RecipeBody({required this.recipe, required this.settings});

  final RecipeRecord recipe;
  final AppSettings settings;

  @override
  Widget build(BuildContext context) {
    final nutrition = recipe.nutrition;
    final allergens = recipe.allergens;
    final uncertain = allergens.needsCheck.difference(allergens.detected);
    return ListView(
      key: const Key('server-recipe-detail'),
      padding: const EdgeInsets.fromLTRB(22, 8, 22, 28),
      children: [
        if (recipe.imageLarge ?? recipe.imageSmall case final url?) ...[
          ClipRRect(
            borderRadius: BorderRadius.circular(24),
            child: Image.network(
              url,
              height: 240,
              width: double.infinity,
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) => const SizedBox.shrink(),
            ),
          ),
          const SizedBox(height: 22),
        ],
        Text(recipe.name, style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            if (recipe.cookingMethod case final method?) Tag(method),
            for (final name in allergens.detected)
              Tag(
                '${appAllergenName(name)} 포함',
                color: const Color(0xFFAE652F),
              ),
            for (final name in uncertain)
              Tag('${appAllergenName(name)} 확인 필요', color: muted),
          ],
        ),
        if (!allergens.complete) ...[
          const SizedBox(height: 12),
          const Notice('재료 분석이 끝나지 않은 레시피예요. 알레르기 재료는 원재료를 직접 확인해 주세요.'),
        ],
        const SectionTitle('영양 정보'),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            _NutrientBox('열량', _amount(null, nutrition.energyKcal, 'kcal')),
            _NutrientBox('단백질', _amount(null, nutrition.proteinG, 'g')),
            _NutrientBox('탄수화물', _amount(null, nutrition.carbohydrateG, 'g')),
            _NutrientBox('나트륨', _amount(null, nutrition.sodiumMg, 'mg')),
          ],
        ),
        const SizedBox(height: 10),
        const Text(
          '공공데이터 제공 수치예요. 1인분 기준이 확인되지 않아 참고로만 봐 주세요.',
          style: TextStyle(fontSize: 13, color: muted),
        ),
        if (nutrition.suspect) ...[
          const SizedBox(height: 10),
          const Notice('열량과 영양소 수치가 서로 맞지 않아 확인이 필요한 값이에요.'),
        ],
        SectionTitle(
          '준비할 재료',
          trailing: recipe.ingredients.isEmpty
              ? null
              : IconButton(
                  tooltip: '재료 읽어주기',
                  onPressed: () =>
                      readAloud(context, settings, _ingredientsSpeech()),
                  icon: const Icon(Icons.volume_up_outlined, color: green),
                ),
        ),
        if (recipe.ingredients.isEmpty)
          const Notice('재료 정보가 제공되지 않았어요.')
        else
          _IngredientGroups(items: recipe.ingredients),
        SectionTitle(
          '조리 방법',
          trailing: recipe.steps.isEmpty
              ? null
              : IconButton(
                  tooltip: '전체 조리 방법 읽어주기',
                  onPressed: () => readAloud(
                    context,
                    settings,
                    recipe.steps.map((s) => '${s.no}. ${s.text}').join('\n'),
                  ),
                  icon: const Icon(Icons.volume_up_outlined, color: green),
                ),
        ),
        if (recipe.steps.isEmpty)
          const Notice('원본 데이터에 조리 방법이 제공되지 않았어요.')
        else ...[
          if (recipe.missingStepNos.isNotEmpty) ...[
            Notice(
              '원본 데이터에 ${recipe.missingStepNos.join('·')}단계가 없어 제공된 단계만 표시해요.',
            ),
            const SizedBox(height: 16),
          ],
          for (final step in recipe.steps)
            Padding(
              key: Key('server-recipe-step-${step.no}'),
              padding: const EdgeInsets.only(bottom: 20),
              child: Text(
                '${step.no}. ${step.text}',
                style: Theme.of(context).textTheme.bodyLarge,
              ),
            ),
        ],
        if (recipe.sodiumTip case final tip?) ...[
          const SectionTitle('나트륨 줄이는 팁'),
          Notice(tip),
        ],
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
    );
  }

  String _ingredientsSpeech() => [
    for (final item in recipe.ingredients)
      [item.name, ?item.amountText].join(' '),
  ].join(', ');
}

/// 재료를 원천의 묶음(section) 순서대로 보여준다.
class _IngredientGroups extends StatelessWidget {
  const _IngredientGroups({required this.items});

  final List<RecipeIngredientItem> items;

  @override
  Widget build(BuildContext context) {
    final groups = <String?, List<RecipeIngredientItem>>{};
    for (final item in items) {
      (groups[item.section] ??= []).add(item);
    }
    return Column(
      key: const Key('server-recipe-ingredients'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final group in groups.entries) ...[
          if (group.key case final title?)
            Padding(
              padding: const EdgeInsets.only(top: 8, bottom: 8),
              child: Text(
                title,
                style: const TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w700,
                  color: green,
                  height: 1.5,
                ),
              ),
            ),
          Container(
            margin: const EdgeInsets.only(bottom: 12),
            decoration: BoxDecoration(
              color: const Color(0xFFF5F8F6),
              border: Border.all(color: line),
              borderRadius: BorderRadius.circular(12),
            ),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (var i = 0; i < group.value.length; i++) ...[
                  if (i > 0) const Divider(height: 1),
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    child: Wrap(
                      alignment: WrapAlignment.spaceBetween,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      spacing: 16,
                      runSpacing: 6,
                      children: [
                        Text(
                          group.value[i].name,
                          style: const TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            height: 1.5,
                          ),
                        ),
                        if (group.value[i].amountText case final amount?)
                          Text(
                            amount,
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

class _NutrientBox extends StatelessWidget {
  const _NutrientBox(this.label, this.value);

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

/// 값이 없으면 0이 아니라 '정보 없음'으로 보여준다.
String _amount(String? label, double? value, String unit) {
  final text = value == null ? '정보 없음' : '${value.toStringAsFixed(0)} $unit';
  return label == null ? text : '$label $text';
}
