import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import '../core/network/api_exception.dart';
import '../data/ai_api.dart';
import '../data/intake_api.dart';
import '../models/ai.dart';
import '../models/intake.dart';
import '../widgets/async_state_view.dart';
import '../widgets/common.dart';
import 'intake_screens.dart';

class IngredientReviewScreen extends StatefulWidget {
  const IngredientReviewScreen({
    required this.aiApi,
    required this.intakeApi,
    required this.name,
    required this.grams,
    super.key,
  });
  final AiApi aiApi;
  final IntakeApi intakeApi;
  final String name;
  final int grams;
  @override
  State<IngredientReviewScreen> createState() => _IngredientReviewScreenState();
}

class _IngredientReviewScreenState extends State<IngredientReviewScreen> {
  IngredientEstimate? _result;
  ApiException? _error;
  CancelToken? _request;
  bool _loading = true;
  List<FoodSelection?> _items = [];
  List<bool> _included = [];
  FoodOrigin _origin(IngredientGuess row, IngredientEstimate result) =>
      FoodOrigin(
        method: 'ingredient_estimate',
        recognizedName: widget.name,
        ingredientName: row.name,
        referenceRecipeName: result.referenceName,
        quantityBasis: 'ai_estimate',
      );
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (_request != null && _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    final request = _request = CancelToken();
    try {
      final result = await widget.aiApi.ingredients(
        widget.name,
        widget.grams,
        request,
      );
      if (!mounted || request.isCancelled) return;
      setState(() {
        _result = result;
        _items = [
          for (final row in result.ingredients)
            row.matches
                .where((m) => !m.isSimilar)
                .firstOrNull
                ?.portion(1, origin: _origin(row, result)),
        ];
        _included = [for (final row in result.ingredients) !row.isWater];
      });
    } on ApiException catch (error) {
      if (mounted && !request.isCancelled) setState(() => _error = error);
    } finally {
      if (mounted && !request.isCancelled) setState(() => _loading = false);
    }
  }

  @override
  void dispose() {
    _request?.cancel();
    super.dispose();
  }

  Future<void> _find(int index) async {
    final food = await Navigator.of(context).push<FoodChoice>(
      MaterialPageRoute(
        builder: (_) => FoodSearchScreen(
          api: widget.intakeApi,
          initialQuery: _result!.ingredients[index].name,
        ),
      ),
    );
    if (food == null || !mounted) return;
    setState(
      () => _items[index] = FoodSelection(
        food,
        _result!.ingredients[index].grams,
        'g',
        estimated: true,
        origin: _origin(_result!.ingredients[index], _result!),
      ),
    );
  }

  Future<void> _amount(int index) async {
    final item = _items[index]!;
    final changed = await showFoodPortionDialog(
      context,
      item.food,
      initial: item,
    );
    if (changed != null && mounted) setState(() => _items[index] = changed);
  }

  @override
  Widget build(BuildContext context) {
    final result = _result;
    final selected = [
      for (var i = 0; i < _items.length; i++)
        if (_included[i] && _items[i] != null) _items[i]!,
    ];
    final unresolved = _included.asMap().entries.any(
      (e) => e.value && _items[e.key] == null,
    );
    final omitted =
        result != null &&
        result.ingredients.asMap().entries.any(
          (e) => !_included[e.key] && !e.value.isWater,
        );
    return Scaffold(
      appBar: AppBar(title: const Text('예상 재료 확인')),
      body: AsyncStateView(
        loading: _loading,
        isEmpty: result == null,
        error: _error,
        onRetry: _load,
        loadingMessage: '1인분의 예상 재료를 찾고 있어요',
        builder: (_) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(widget.name, style: Theme.of(context).textTheme.titleLarge),
            Notice(result!.notice),
            if (result.referenceName != null)
              Text(
                '공공 레시피 ${result.referenceName}의 재료 구성을 참고했어요. 분량은 AI가 1인분으로 예상했어요.',
              ),
            const Text('없는 재료는 체크를 빼고, 양이나 음식 종류가 다르면 바꿔 주세요.'),
            for (var i = 0; i < result.ingredients.length; i++)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(result.ingredients[i].name),
                        subtitle: Text(
                          'AI 예상 ${result.ingredients[i].grams} g',
                        ),
                        value: _included[i],
                        onChanged: result.ingredients[i].isWater
                            ? null
                            : (value) => setState(() => _included[i] = value!),
                      ),
                      if (result.ingredients[i].isWater)
                        const Text('조리용 물은 영양 합산에서 제외해요.')
                      else ...[
                        if (_items[i] case final item?) ...[
                          Text('연결한 식품: ${item.food.name}'),
                          Text('계산할 양: ${item.amount} ${item.unit} · 예상값'),
                          TextButton(
                            onPressed: () => _amount(i),
                            child: const Text('양 바꾸기'),
                          ),
                        ] else ...[
                          const Text('연결할 식품을 골라 주세요. 찾지 못한 재료를 0으로 계산하지 않아요.'),
                          for (final match in result.ingredients[i].matches)
                            OutlinedButton(
                              onPressed: () => setState(
                                () => _items[i] = match.portion(
                                  1,
                                  origin: _origin(
                                    result.ingredients[i],
                                    result,
                                  ),
                                ),
                              ),
                              child: Text('${match.food.name} 선택 · 확인 필요'),
                            ),
                        ],
                        TextButton(
                          onPressed: () => _find(i),
                          child: const Text('재료 다시 찾기'),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            if (unresolved)
              const Notice('체크한 재료를 모두 연결하거나, 계산에서 뺄 재료의 체크를 해제해 주세요.'),
            if (omitted)
              const Notice('체크를 뺀 재료의 영양은 합계에 포함되지 않아요. 전체 요리의 영양값과 다를 수 있어요.'),
            FilledButton(
              key: const Key('ingredients-confirm'),
              onPressed: selected.isEmpty || unresolved
                  ? null
                  : () => Navigator.pop(
                      context,
                      IngredientReviewSelection(selected, [
                        for (var i = 0; i < result.ingredients.length; i++)
                          if (!_included[i])
                            ExcludedIngredient(
                              widget.name,
                              result.ingredients[i].name,
                              result.ingredients[i].isWater
                                  ? 'water'
                                  : _items[i] == null
                                  ? 'unmatched'
                                  : 'user_excluded',
                            ),
                      ]),
                    ),
              child: Text(omitted ? '빠진 재료가 있는 참고값으로 계속' : '이 재료와 양으로 계속'),
            ),
          ],
        ),
      ),
    );
  }
}
