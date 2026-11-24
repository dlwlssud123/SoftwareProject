import 'package:flutter/material.dart';

import '../data/intake_api.dart';
import '../models/ai.dart';
import '../models/intake.dart';
import '../widgets/common.dart';
import 'intake_screens.dart';

class PhotoFoodScreen extends StatefulWidget {
  const PhotoFoodScreen({required this.result, required this.api, super.key});
  final PhotoRecognition result;
  final IntakeApi api;
  @override
  State<PhotoFoodScreen> createState() => _PhotoFoodScreenState();
}

class _PhotoFoodScreenState extends State<PhotoFoodScreen> {
  late final _matches = [
    for (final dish in widget.result.foods) dish.matches.firstOrNull,
  ];
  late final _factors = List.filled(widget.result.foods.length, 1.0);
  late final _included = List.filled(widget.result.foods.length, true);

  Future<void> _find(int index) async {
    final food = await Navigator.of(context).push<FoodChoice>(
      MaterialPageRoute(builder: (_) => FoodSearchScreen(api: widget.api)),
    );
    if (food == null || !mounted) return;
    setState(() {
      _matches[index] = PhotoMatch(
        food,
        widget.result.foods[index].grams.toDouble(),
        'g',
        'AI가 제안한 대략적인 1인분이에요. 실제 양에 맞게 바꿔 주세요.',
      );
      _included[index] = true;
    });
  }

  Future<void> _confirm() async {
    final selections = [
      for (var i = 0; i < _matches.length; i++)
        if (_included[i] && _matches[i] != null)
          _matches[i]!.portion(_factors[i]),
    ];
    final saved = await Navigator.of(context).push<SavedIntake>(
      MaterialPageRoute(
        builder: (_) => IntakeEditor(api: widget.api, initialItems: selections),
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
          (e) => !e.value || _matches[e.key] != null,
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
                    if (_matches[i] case final match?) ...[
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
                          decoration: const InputDecoration(
                            labelText: '맞는 음식 고르기',
                          ),
                          items: [
                            for (final choice in widget.result.foods[i].matches)
                              DropdownMenuItem(
                                value: choice,
                                child: Text(choice.food.name, maxLines: 2),
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
                    ] else
                      const Text('연결할 영양 DB 음식을 찾지 못했어요. 직접 찾아 주세요.'),
                    OutlinedButton(
                      onPressed: () => _find(i),
                      child: const Text('다른 음식 검색'),
                    ),
                  ],
                ),
              ),
            ),
          if (widget.result.foods.isNotEmpty) ...[
            const Text('맞지 않는 음식은 체크를 빼 주세요. 다음 화면에서 영양을 확인한 뒤 저장해요.'),
            FilledButton(
              onPressed: canConfirm ? _confirm : null,
              child: const Text('이 음식으로 영양 확인'),
            ),
          ],
        ],
      ),
    );
  }
}
