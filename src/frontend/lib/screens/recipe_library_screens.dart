import 'package:flutter/material.dart';

import '../core/network/api_exception.dart';
import '../data/recipe_api.dart';
import '../data/recipe_library_api.dart';
import '../models/recipe_record.dart';
import '../services/settings.dart';
import '../widgets/async_state_view.dart';
import '../widgets/common.dart';
import '../widgets/recipe_actions.dart';
import 'server_recipe_screens.dart';
import 'shopping_list_screen.dart';

class MealPlanScreen extends StatefulWidget {
  const MealPlanScreen({
    required this.library,
    required this.recipes,
    required this.settings,
    super.key,
  });

  final RecipeLibraryApi library;
  final RecipeApi recipes;
  final AppSettings settings;

  @override
  State<MealPlanScreen> createState() => _MealPlanScreenState();
}

class _MealPlanScreenState extends State<MealPlanScreen> {
  DateTime _date = DateUtils.dateOnly(DateTime.now());
  late Future<Map<MealSlot, PlanEntry>> _plan = widget.library.plan(_date);
  bool _busy = false;

  void _load() => setState(() {
    _plan = widget.library.plan(_date);
  });

  Future<void> _changeDate() async {
    final selected = await choosePlanDate(context, _date);
    if (selected == null || !mounted) return;
    setState(() {
      _date = selected;
      _plan = widget.library.plan(_date);
    });
  }

  Future<void> _edit(MealSlot slot, {bool remove = false}) async {
    setState(() => _busy = true);
    try {
      if (remove) {
        await widget.library.removeMeal(_date, slot);
      } else {
        final record = await Navigator.of(context).push<RecipeRecord>(
          MaterialPageRoute(
            builder: (_) => ServerRecipeList(
              api: widget.recipes,
              settings: widget.settings,
              pickRecipe: true,
            ),
          ),
        );
        if (record == null || !mounted) return;
        await widget.library.putMeal(
          _date,
          slot,
          RecipeChoice(
            record.recipeId,
            record.name,
            revisionId: record.revisionId,
          ),
        );
      }
      if (mounted) {
        _load();
        showMessage(context, remove ? '식단에서 뺐어요.' : '${slot.label} 식단에 담았어요.');
      }
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _open(RecipeChoice recipe) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ServerRecipeDetail(
          api: widget.recipes,
          recipeId: recipe.id,
          settings: widget.settings,
          library: widget.library,
        ),
      ),
    );
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('내 식단')),
    body: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: OutlinedButton.icon(
            onPressed: _busy ? null : _changeDate,
            icon: const Icon(Icons.calendar_month_outlined),
            label: Text(
              MaterialLocalizations.of(context).formatFullDate(_date),
            ),
          ),
        ),
        Expanded(
          child: FutureBuilder<Map<MealSlot, PlanEntry>>(
            future: _plan,
            builder: (context, snapshot) => AsyncStateView(
              loading: snapshot.connectionState != ConnectionState.done,
              error: snapshot.error as ApiException?,
              onRetry: _load,
              isEmpty: false,
              builder: (context) => ListView(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
                children: [
                  FilledButton.icon(
                    key: const Key('plan-shopping-start'),
                    onPressed: _busy
                        ? null
                        : () => Navigator.of(context).push(
                            MaterialPageRoute<void>(
                              builder: (_) => ShoppingListScreen(
                                library: widget.library,
                                date: _date,
                              ),
                            ),
                          ),
                    icon: const Icon(Icons.shopping_basket_outlined),
                    label: const Text('이 날의 장보기 목록'),
                  ),
                  for (final slot in MealSlot.values) ...[
                    SectionTitle(slot.label),
                    if (snapshot.data?[slot] case final entry?) ...[
                      if (entry.isActive)
                        FeatureTile(
                          title: entry.recipe.name,
                          subtitle: '레시피 자세히 보기',
                          icon: Icons.restaurant_menu_outlined,
                          onTap: () => _open(entry.recipe),
                        )
                      else
                        Notice('${entry.recipe.name} · 저장할 때의 레시피가 갱신됐어요.'),
                    ] else
                      const Text('아직 담은 메뉴가 없어요.'),
                    Wrap(
                      spacing: 8,
                      children: [
                        OutlinedButton(
                          onPressed: _busy ? null : () => _edit(slot),
                          child: Text(
                            snapshot.data?[slot] == null ? '메뉴 고르기' : '메뉴 바꾸기',
                          ),
                        ),
                        if (snapshot.data?[slot] != null)
                          TextButton(
                            onPressed: _busy
                                ? null
                                : () => _edit(slot, remove: true),
                            child: const Text('식단에서 빼기'),
                          ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ],
    ),
  );
}

class SavedRecipesScreen extends StatefulWidget {
  const SavedRecipesScreen({
    required this.library,
    required this.recipes,
    required this.settings,
    super.key,
  });

  final RecipeLibraryApi library;
  final RecipeApi recipes;
  final AppSettings settings;

  @override
  State<SavedRecipesScreen> createState() => _SavedRecipesScreenState();
}

class _SavedRecipesScreenState extends State<SavedRecipesScreen> {
  int _offset = 0;
  late Future<SavedRecipesPage> _page = widget.library.saved();
  bool _removing = false;

  void _load(int offset) => setState(() {
    _offset = offset;
    _page = widget.library.saved(offset: offset);
  });

  Future<void> _open(SavedRecipeItem item) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ServerRecipeDetail(
          api: widget.recipes,
          recipeId: item.id,
          settings: widget.settings,
          library: widget.library,
        ),
      ),
    );
    if (mounted) _load(0);
  }

  Future<void> _remove(SavedRecipeItem item) async {
    setState(() => _removing = true);
    try {
      await widget.library.setSaved(item.id, false);
      if (mounted) _load(0);
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.message);
    } finally {
      if (mounted) setState(() => _removing = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('저장한 레시피')),
    body: FutureBuilder<SavedRecipesPage>(
      future: _page,
      builder: (context, snapshot) {
        final page = snapshot.data;
        return AsyncStateView(
          loading: snapshot.connectionState != ConnectionState.done,
          error: snapshot.error as ApiException?,
          onRetry: () => _load(_offset),
          isEmpty: page?.items.isEmpty != false,
          emptyMessage: '저장한 레시피가 없어요. 레시피를 열어 저장해 보세요.',
          builder: (context) => ListView(
            padding: const EdgeInsets.all(16),
            children: [
              for (final item in page!.items)
                if (item.name case final name?)
                  FeatureTile(
                    title: name,
                    subtitle: '레시피 자세히 보기',
                    icon: Icons.bookmark_outline,
                    onTap: () => _open(item),
                  )
                else
                  ListTile(
                    title: const Text('현재 이용할 수 없는 레시피'),
                    trailing: TextButton(
                      onPressed: _removing ? null : () => _remove(item),
                      child: const Text('저장 해제'),
                    ),
                  ),
              Wrap(
                spacing: 10,
                children: [
                  if (_offset > 0)
                    OutlinedButton(
                      onPressed: () => _load(_offset - 20),
                      child: const Text('이전 목록'),
                    ),
                  if (_offset + page.items.length < page.total)
                    OutlinedButton(
                      onPressed: () => _load(_offset + page.items.length),
                      child: const Text('다음 목록'),
                    ),
                ],
              ),
            ],
          ),
        );
      },
    ),
  );
}
