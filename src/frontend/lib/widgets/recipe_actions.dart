import 'package:flutter/material.dart';

import '../core/network/api_exception.dart';
import '../data/recipe_library_api.dart';
import 'common.dart';

Future<DateTime?> choosePlanDate(BuildContext context, DateTime initial) =>
    showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime(2000),
      lastDate: DateTime(2100, 12, 31),
      helpText: '식단 날짜 선택',
    );

class RecipeActions extends StatefulWidget {
  const RecipeActions({required this.api, required this.recipe, super.key});

  final RecipeLibraryApi api;
  final RecipeChoice recipe;

  @override
  State<RecipeActions> createState() => _RecipeActionsState();
}

class _RecipeActionsState extends State<RecipeActions> {
  late Future<bool> _saved = widget.api.isSaved(widget.recipe.id);
  bool _saving = false, _adding = false;

  Future<void> _toggle(bool saved) async {
    setState(() => _saving = true);
    try {
      await widget.api.setSaved(widget.recipe.id, !saved);
      if (!mounted) return;
      setState(() {
        _saved = Future.value(!saved);
      });
      showMessage(context, saved ? '저장을 해제했어요.' : '레시피를 저장했어요.');
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _addToPlan() async {
    setState(() => _adding = true);
    try {
      final date = await choosePlanDate(context, DateTime.now());
      if (date == null || !mounted) return;
      final slot = await showDialog<MealSlot>(
        context: context,
        builder: (context) => SimpleDialog(
          title: const Text('어느 끼니에 담을까요?'),
          children: [
            for (final slot in MealSlot.values)
              SimpleDialogOption(
                padding: const EdgeInsets.symmetric(
                  horizontal: 24,
                  vertical: 14,
                ),
                onPressed: () => Navigator.of(context).pop(slot),
                child: Text(
                  slot.label,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
          ],
        ),
      );
      if (slot == null || !mounted) return;
      final existing = (await widget.api.plan(date))[slot];
      if (!mounted) return;
      if (existing != null && existing.recipe.id != widget.recipe.id) {
        final replace = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text('${slot.label} 메뉴를 바꿀까요?'),
            content: Text(
              '${existing.recipe.name}에서 ${widget.recipe.name}(으)로 바꿔요.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('취소'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('메뉴 바꾸기'),
              ),
            ],
          ),
        );
        if (replace != true || !mounted) return;
      }
      await widget.api.putMeal(date, slot, widget.recipe);
      if (mounted) showMessage(context, '${slot.label} 식단에 담았어요.');
    } on ApiException catch (error) {
      if (mounted) showMessage(context, error.message);
    } finally {
      if (mounted) setState(() => _adding = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 12),
    child: Wrap(
      spacing: 10,
      runSpacing: 6,
      children: [
        OutlinedButton.icon(
          onPressed: _adding ? null : _addToPlan,
          icon: const Icon(Icons.event_available_outlined),
          label: Text(_adding ? '처리 중이에요' : '식단표에 담기'),
        ),
        FutureBuilder<bool>(
          future: _saved,
          builder: (context, snapshot) {
            final saved = snapshot.data ?? false;
            return OutlinedButton.icon(
              onPressed:
                  snapshot.connectionState != ConnectionState.done || _saving
                  ? null
                  : snapshot.hasError
                  ? () => setState(() {
                      _saved = widget.api.isSaved(widget.recipe.id);
                    })
                  : () => _toggle(saved),
              icon: Icon(saved ? Icons.bookmark : Icons.bookmark_border),
              label: Text(
                snapshot.hasError
                    ? '저장 상태 다시 확인'
                    : saved
                    ? '저장 해제'
                    : '레시피 저장',
              ),
            );
          },
        ),
      ],
    ),
  );
}
