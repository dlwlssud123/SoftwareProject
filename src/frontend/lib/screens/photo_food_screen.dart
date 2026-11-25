import 'package:flutter/material.dart';

import '../data/intake_api.dart';
import '../data/ai_api.dart';
import '../models/ai.dart';
import '../models/intake.dart';
import '../models/recommendations.dart' show nutrientLabel;
import '../widgets/common.dart';
import 'intake_screens.dart';
import 'ingredient_review_screen.dart';

class PhotoFoodScreen extends StatefulWidget {
  const PhotoFoodScreen({
    required this.result,
    required this.api,
    this.aiApi,
    super.key,
  });
  final PhotoRecognition result;
  final IntakeApi api;
  final AiApi? aiApi;
  @override
  State<PhotoFoodScreen> createState() => _PhotoFoodScreenState();
}

class _PhotoFoodScreenState extends State<PhotoFoodScreen> {
  late final _matches = [
    for (final dish in widget.result.foods)
      dish.matches.where((match) => !match.isSimilar).firstOrNull,
  ];
  late final _factors = List.filled(widget.result.foods.length, 1.0);
  late final _included = List.filled(widget.result.foods.length, true);
  final _ingredients = <int, IngredientReviewSelection>{};

  Future<void> _estimateIngredients(int index) async {
    final api = widget.aiApi;
    if (api == null) return;
    final dish = widget.result.foods[index];
    final items = await Navigator.of(context).push<IngredientReviewSelection>(
      MaterialPageRoute(
        builder: (_) => IngredientReviewScreen(
          aiApi: api,
          intakeApi: widget.api,
          name: dish.name,
          grams: dish.grams,
        ),
      ),
    );
    if (items == null || items.items.isEmpty || !mounted) return;
    setState(() {
      _ingredients[index] = items;
      _included[index] = true;
      _matches[index] = null;
    });
  }

  Future<void> _find(int index) async {
    final food = await Navigator.of(context).push<FoodChoice>(
      MaterialPageRoute(
        builder: (_) => FoodSearchScreen(
          api: widget.api,
          initialQuery: widget.result.foods[index].name,
        ),
      ),
    );
    if (food == null || !mounted) return;
    setState(() {
      _ingredients.remove(index);
      _matches[index] = PhotoMatch(
        food,
        widget.result.foods[index].grams.toDouble(),
        'g',
        'AI가 제안한 대략적인 1인분이에요. 실제 양에 맞게 바꿔 주세요.',
        manuallySelected: true,
      );
      _included[index] = true;
    });
  }

  double _ingredientAmount(FoodSelection item, int index) => double.parse(
    (item.amount * _factors[index])
        .clamp(0.001, double.infinity)
        .toStringAsFixed(3),
  );

  Future<void> _confirm() async {
    final selections = [
      for (var i = 0; i < _matches.length; i++)
        if (_included[i] && _matches[i] != null)
          _matches[i]!.portion(
            _factors[i],
            recognizedName: widget.result.foods[i].name,
          ),
      for (var i = 0; i < _matches.length; i++)
        if (_included[i])
          for (final item in _ingredients[i]?.items ?? <FoodSelection>[])
            FoodSelection(
              item.food,
              _ingredientAmount(item, i),
              item.unit,
              estimated: true,
              origin: _factors[i] == 1 ? item.origin : item.origin?.adjusted(),
            ),
    ];
    final saved = await Navigator.of(context).push<SavedIntake>(
      MaterialPageRoute(
        builder: (_) => IntakeEditor(
          api: widget.api,
          initialItems: selections,
          initialContext: AnalysisContext([
            for (final entry in _ingredients.entries)
              if (_included[entry.key]) ...entry.value.excluded,
          ]),
          initialNotice: _ingredients.keys.any((i) => _included[i])
              ? '예상한 1인분 재료를 기준으로 계산한 참고값이에요. 체크를 뺀 재료나 빠진 기름·양념의 영양은 합계에 포함되지 않아요.'
              : null,
        ),
      ),
    );
    if (saved != null && mounted) {
      Navigator.pop(context, saved);
    }
  }

  @override
  Widget build(BuildContext context) {
    final canConfirm =
        _included.asMap().entries.any((e) => e.value) &&
        _included.asMap().entries.every(
          (e) =>
              !e.value ||
              _matches[e.key] != null ||
              _ingredients.containsKey(e.key),
        );
    final itemCount = [
      for (var i = 0; i < _matches.length; i++)
        if (_included[i])
          _ingredients[i]?.items.length ?? (_matches[i] == null ? 0 : 1),
    ].fold<int>(0, (sum, count) => sum + count);
    final withinQuantity = _ingredients.entries.every(
      (entry) =>
          !_included[entry.key] ||
          entry.value.items.every(
            (item) => _ingredientAmount(item, entry.key) <= 10000,
          ),
    );
    return Scaffold(
      appBar: AppBar(title: const Text('음식과 먹은 양 확인')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 112),
        children: [
          Notice(widget.result.notice),
          if (widget.result.foods.isEmpty) ...[
            const Text('음식을 찾지 못했어요. 다른 사진을 선택하거나 직접 입력해 주세요.'),
            FilledButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => IntakeEditor(api: widget.api),
                ),
              ),
              child: const Text('음식 직접 입력'),
            ),
          ],
          for (var i = 0; i < widget.result.foods.length; i++)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(widget.result.foods[i].name),
                      value: _included[i],
                      onChanged: (value) =>
                          setState(() => _included[i] = value!),
                    ),
                    if (widget.result.foods[i].confidence != 'high')
                      const Text('음식 이름이 맞는지 꼭 확인해 주세요.'),
                    if (_ingredients[i] case final result?) ...[
                      const Notice('확인한 예상 재료의 영양을 합산해요. 실제 재료와 양에 따라 달라요.'),
                      for (final item in result.items)
                        Text(
                          '${item.food.name} · ${_ingredientAmount(item, i)} ${item.unit}',
                        ),
                      const Text('재료의 양과 종류는 다음 화면에서도 바꿀 수 있어요.'),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          for (final (factor, label) in [
                            (0.5, '반 정도'),
                            (1.0, '1인분'),
                            (1.5, '조금 많이'),
                          ])
                            ChoiceChip(
                              label: Text(label),
                              selected: _factors[i] == factor,
                              onSelected: (_) =>
                                  setState(() => _factors[i] = factor),
                            ),
                        ],
                      ),
                    ] else if (_matches[i] case final match?) ...[
                      if (match.isSimilar)
                        Notice(
                          '${widget.result.foods[i].name} 대신 ${match.food.name}의 영양정보로 대략 계산해요. 재료와 조리법에 따라 달라요.',
                        ),
                      Text(
                        '영양 DB 음식: ${match.food.name}',
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      if (widget.result.foods[i].matches.length > 1)
                        DropdownButtonFormField<PhotoMatch>(
                          key: ObjectKey(match),
                          initialValue:
                              widget.result.foods[i].matches.contains(match)
                              ? match
                              : null,
                          isExpanded: true,
                          itemHeight: null,
                          decoration: const InputDecoration(
                            labelText: '맞는 음식 고르기',
                          ),
                          items: [
                            for (final choice in widget.result.foods[i].matches)
                              DropdownMenuItem(
                                value: choice,
                                child: Text(choice.food.name),
                              ),
                          ],
                          onChanged: (value) {
                            if (value != null) {
                              setState(() => _matches[i] = value);
                            }
                          },
                        ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          for (final (factor, label) in [
                            (0.5, '반 정도'),
                            (1.0, '1인분'),
                            (1.5, '조금 많이'),
                          ])
                            ChoiceChip(
                              label: Text(label),
                              selected: _factors[i] == factor,
                              onSelected: (_) =>
                                  setState(() => _factors[i] = factor),
                              materialTapTargetSize:
                                  MaterialTapTargetSize.padded,
                            ),
                        ],
                      ),
                      Text(
                        '예상 ${match.amount * _factors[i]} ${match.unit} · ${_factors[i]}인분',
                      ),
                      Text(match.description),
                    ] else if (widget.result.foods[i].matches.isNotEmpty) ...[
                      const Notice(
                        '같은 음식을 찾지 못했어요. 이름이 비슷한 음식의 참고 영양정보예요. 재료와 조리법이 가까운 음식을 골라 주세요.',
                      ),
                      for (final choice in widget.result.foods[i].matches)
                        OutlinedButton(
                          onPressed: () => setState(() => _matches[i] = choice),
                          child: Text(
                            [
                              '${choice.food.name} 선택',
                              '${choice.food.basisText ?? 'DB 기준량'} 기준 · 참고값',
                              if (choice.nutrients case final nutrients?)
                                for (final entry
                                    in IntakeNutrients.labels.entries)
                                  '${entry.value.$1} ${nutrientLabel(nutrients.values[entry.key], entry.value.$2)}',
                            ].join('\n'),
                          ),
                        ),
                    ] else ...[
                      const Text('비슷한 음식도 찾지 못했어요. 음식 이름을 바꿔 직접 찾아 주세요.'),
                      if (widget.aiApi != null) ...[
                        const Text(
                          '음식 이름을 NVIDIA AI로 보내 일반적인 1인분 재료와 양을 예상할 수 있어요. 사진은 다시 보내지 않아요.',
                        ),
                        FilledButton(
                          onPressed: () => _estimateIngredients(i),
                          child: const Text('AI로 재료 추정하기'),
                        ),
                      ],
                    ],
                    OutlinedButton(
                      onPressed: () => _find(i),
                      child: const Text('다른 음식 검색'),
                    ),
                  ],
                ),
              ),
            ),
          if (widget.result.foods.isNotEmpty) ...[
            if (!withinQuantity) const Notice('재료 한 개의 양이 너무 많아요. 분량을 줄여 주세요.'),
            if (itemCount > 30)
              const Notice(
                '한 번에 음식과 재료 30개까지 담을 수 있어요. 일부 음식의 체크를 빼고 나누어 기록해 주세요.',
              ),
            const Text('맞지 않는 음식은 체크를 빼 주세요. 다음 화면에서 영양을 확인한 뒤 저장해요.'),
            FilledButton(
              onPressed: canConfirm && itemCount <= 30 && withinQuantity
                  ? _confirm
                  : null,
              child: const Text('이 음식으로 영양 확인'),
            ),
          ],
        ],
      ),
    );
  }
}
