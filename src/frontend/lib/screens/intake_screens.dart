import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/network/api_exception.dart';
import '../data/intake_api.dart';
import '../models/intake.dart';
import '../models/recommendations.dart' show nutrientLabel;
import '../widgets/async_state_view.dart';
import '../widgets/common.dart';
import '../widgets/intake_evidence_view.dart';

String _when(BuildContext context, DateTime instant) {
  final wall = koreanTime(instant), locale = MaterialLocalizations.of(context);
  return '${locale.formatMediumDate(wall)} ${TimeOfDay(hour: wall.hour, minute: wall.minute).format(context)}';
}

class IntakeNutrientView extends StatelessWidget {
  const IntakeNutrientView(this.total, {super.key});
  final IntakeTotal total;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      for (final entry in IntakeNutrients.labels.entries)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Wrap(
            alignment: WrapAlignment.spaceBetween,
            spacing: 16,
            runSpacing: 4,
            children: [
              Text(entry.value.$1, style: const TextStyle(fontSize: 18)),
              Text(
                nutrientLabel(
                  total.nutrients.values[entry.key],
                  entry.value.$2,
                ),
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ),
      if (!total.complete)
        const Notice('계산하지 못한 음식이 있어요. 합계는 계산 가능한 음식만 반영했어요.'),
      if (total.missing)
        const Notice('원천에 없는 영양 정보는 0으로 채우지 않았어요. 표시된 합계에 빠진 값이 있을 수 있어요.'),
      if (total.approximate > 0) const Notice('g와 mL를 같은 무게로 본 근사값이 포함됐어요.'),
    ],
  );
}

class FoodSearchScreen extends StatefulWidget {
  const FoodSearchScreen({
    required this.api,
    this.initialQuery = '',
    super.key,
  });
  final IntakeApi api;
  final String initialQuery;
  @override
  State<FoodSearchScreen> createState() => _FoodSearchScreenState();
}

class _FoodSearchScreenState extends State<FoodSearchScreen> {
  final _query = TextEditingController();
  Future<FoodPage>? _page;
  String _term = '';
  int _offset = 0;
  @override
  void initState() {
    super.initState();
    _query.text = widget.initialQuery;
    if (widget.initialQuery.trim().isNotEmpty) _search();
  }

  void _search([int offset = 0]) {
    final term = _query.text.trim();
    if (term.isEmpty) {
      showMessage(context, '먹은 음식 이름을 입력해 주세요.');
      return;
    }
    if (term != _term) offset = 0;
    setState(() {
      _term = term;
      _offset = offset;
      _page = widget.api.foods(_term, offset: offset);
    });
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('먹은 음식 찾기')),
    body: Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                key: const Key('food-search'),
                controller: _query,
                maxLength: 100,
                textInputAction: TextInputAction.search,
                decoration: const InputDecoration(
                  labelText: '음식 이름',
                  hintText: '예: 쌀밥, 우유',
                ),
                onSubmitted: (_) => _search(),
              ),
              FilledButton.icon(
                onPressed: () => _search(),
                icon: const Icon(Icons.search),
                label: const Text('음식 찾기'),
              ),
            ],
          ),
        ),
        Expanded(
          child: _page == null
              ? const Center(child: Text('먹은 음식 이름으로 찾아보세요.'))
              : FutureBuilder<FoodPage>(
                  future: _page,
                  builder: (context, snapshot) => AsyncStateView(
                    loading: snapshot.connectionState != ConnectionState.done,
                    error: snapshot.error as ApiException?,
                    onRetry: () => _search(_offset),
                    isEmpty: snapshot.data?.items.isEmpty ?? false,
                    emptyMessage: '맞는 음식을 찾지 못했어요. 다른 이름으로 찾아보세요.',
                    builder: (context) {
                      final page = snapshot.data!;
                      return ListView(
                        padding: const EdgeInsets.all(16),
                        children: [
                          const Notice(
                            '음식 이름과 기준량을 확인하고 골라 주세요. 비슷한 이름의 다른 음식이 있을 수 있어요.',
                          ),
                          for (final food in page.items)
                            FeatureTile(
                              key: Key('food-result-${food.id}'),
                              title: food.name,
                              subtitle: [
                                if (food.category != null) food.category!,
                                '기준량: ${food.basisText ?? '확인 필요'}',
                                if (food.hasServing)
                                  '원천 1회 분량: ${food.servingReference}',
                              ].join('\n'),
                              icon: Icons.restaurant_outlined,
                              onTap: () => Navigator.pop(context, food),
                            ),
                          Wrap(
                            spacing: 12,
                            runSpacing: 8,
                            children: [
                              if (_offset > 0)
                                OutlinedButton(
                                  onPressed: () => _search(_offset - 20),
                                  child: const Text('이전 음식'),
                                ),
                              if (_offset + page.items.length < page.total)
                                OutlinedButton(
                                  onPressed: () => _search(_offset + 20),
                                  child: const Text('다음 음식'),
                                ),
                            ],
                          ),
                        ],
                      );
                    },
                  ),
                ),
        ),
      ],
    ),
  );
}

Future<FoodSelection?> showFoodPortionDialog(
  BuildContext context,
  FoodChoice food, {
  FoodSelection? initial,
}) => showDialog<FoodSelection>(
  context: context,
  builder: (_) => _PortionDialog(food, initial),
);

class _PortionDialog extends StatefulWidget {
  const _PortionDialog(this.food, this.initial);
  final FoodChoice food;
  final FoodSelection? initial;
  @override
  State<_PortionDialog> createState() => _PortionDialogState();
}

class _PortionDialogState extends State<_PortionDialog> {
  late String _unit =
      widget.initial?.unit ??
      (widget.food.hasServing
          ? '인분'
          : widget.food.basisUnit == 'mL'
          ? 'mL'
          : 'g');
  late final _amount = TextEditingController(
    text: (widget.initial?.amount ?? (_unit == '인분' ? 1 : 100)).toString(),
  );
  final _form = GlobalKey<FormState>();
  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text('${widget.food.name} · 먹은 양'),
    content: SingleChildScrollView(
      child: Form(
        key: _form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('원천 기준량: ${widget.food.basisText ?? '확인 필요'}'),
            if (widget.food.hasServing)
              Text('원천 1회 분량: ${widget.food.servingReference}'),
            const SizedBox(height: 12),
            TextFormField(
              key: const Key('food-amount'),
              controller: _amount,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
              ],
              decoration: const InputDecoration(labelText: '먹은 양'),
              validator: (text) {
                final value = double.tryParse(text ?? '');
                if (value == null ||
                    !value.isFinite ||
                    value <= 0 ||
                    value > 10000) {
                  return '양을 0보다 큰 숫자로 확인해 주세요.';
                }
                if (_unit != '인분' &&
                    (value < 0.001 ||
                        (value * 1000 - (value * 1000).round()).abs() >
                            0.000001)) {
                  return 'g와 mL는 소수점 셋째 자리까지 확인해 주세요.';
                }
                return null;
              },
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _unit,
              isExpanded: true,
              decoration: const InputDecoration(labelText: '단위'),
              items: [
                for (final unit in [
                  'g',
                  'mL',
                  if (widget.food.hasServing) '인분',
                ])
                  DropdownMenuItem(
                    value: unit,
                    child: Text(
                      unit == 'g'
                          ? 'g (그램)'
                          : unit == 'mL'
                          ? 'mL (밀리리터)'
                          : '인분',
                    ),
                  ),
              ],
              onChanged: (unit) {
                if (unit != null) {
                  setState(() {
                    _unit = unit;
                    _amount.text = unit == '인분' ? '1' : '100';
                  });
                }
              },
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              children: [
                for (final value
                    in _unit == '인분' ? [0.5, 1, 2] : [50, 100, 150, 200])
                  ActionChip(
                    label: Text('$value $_unit'),
                    onPressed: () => _amount.text = value.toString(),
                  ),
              ],
            ),
            const Text('숫자는 직접 바꿀 수 있어요. 먹은 양을 확인한 뒤 담아 주세요.'),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('취소'),
      ),
      FilledButton(
        onPressed: () {
          if (_form.currentState!.validate()) {
            Navigator.pop(
              context,
              FoodSelection(
                widget.food,
                double.parse(_amount.text),
                _unit,
                estimated: widget.initial?.estimated ?? false,
                origin: widget.initial == null
                    ? const FoodOrigin(
                        method: 'manual',
                        quantityBasis: 'user_entered',
                      )
                    : widget.initial!.amount == double.parse(_amount.text) &&
                          widget.initial!.unit == _unit
                    ? widget.initial!.origin
                    : widget.initial!.origin?.adjusted(),
              ),
            );
          }
        },
        child: const Text('이 양으로 담기'),
      ),
    ],
  );
}

class IntakeEditor extends StatefulWidget {
  const IntakeEditor({
    required this.api,
    this.existing,
    this.initialItems = const [],
    this.initialNotice,
    this.initialContext,
    super.key,
  });
  final IntakeApi api;
  final SavedIntake? existing;
  final List<FoodSelection> initialItems;
  final String? initialNotice;
  final AnalysisContext? initialContext;
  @override
  State<IntakeEditor> createState() => _IntakeEditorState();
}

class _IntakeEditorState extends State<IntakeEditor> {
  late AnalysisContext? _analysisContext = widget.existing != null
      ? widget.existing!.analysisContext
      : widget.initialContext ?? const AnalysisContext([]);
  late final List<FoodSelection> _items = [
    ...(widget.existing?.items ?? widget.initialItems),
  ];
  late DateTime _time = widget.existing?.eatenAt ?? DateTime.now().toUtc();
  IntakePreview? _preview;
  PendingIntake? _pending;
  final _invalid = <int>{};
  bool _busy = false, _loading = true, _restoreFailed = false;
  String? _error;
  bool _conflict = false;
  bool _restoredBeforePhoto = false;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    setState(() {
      _loading = true;
      _restoreFailed = false;
    });
    try {
      final pending = widget.existing == null
          ? await widget.api.pending()
          : null;
      if (!mounted) return;
      setState(() {
        _pending = pending;
        if (pending != null) {
          _restoredBeforePhoto = widget.initialItems.isNotEmpty;
          _items
            ..clear()
            ..addAll(pending.items);
          _time = pending.eatenAt;
          _analysisContext = pending.analysisContext;
        }
        _error = null;
      });
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _error = error.message;
          _restoreFailed = true;
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
    if (mounted &&
        !_restoreFailed &&
        _pending == null &&
        widget.initialItems.isNotEmpty) {
      await _calculate();
    }
  }

  bool get _itemsChanged =>
      jsonEncode(_items.map((e) => e.toJson()).toList()) !=
      jsonEncode(widget.existing?.items.map((e) => e.toJson()).toList());

  Future<void> _repair() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('이전 저장 확인을 새로 시작할까요?'),
        content: const Text('이미 저장된 식사는 지워지지 않아요. 먼저 저장한 식사에서 중복 여부를 확인해 주세요.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('확인했고 다시 입력'),
          ),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await widget.api.clearBrokenPendingAfterReview();
      if (mounted) await _restore();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  bool get _timeOnly => widget.existing != null && !_itemsChanged;
  bool get _canSave =>
      !_busy &&
      !_loading &&
      !_restoreFailed &&
      !_conflict &&
      _items.isNotEmpty &&
      _invalid.isEmpty &&
      (_pending != null ||
          (_timeOnly
              ? _time != widget.existing!.eatenAt
              : _preview?.total.complete == true));

  Future<void> _choose([int? index]) async {
    final food = await Navigator.of(context).push<FoodChoice>(
      MaterialPageRoute(builder: (_) => FoodSearchScreen(api: widget.api)),
    );
    if (food == null || !mounted) return;
    final portion = await showDialog<FoodSelection>(
      context: context,
      builder: (_) => _PortionDialog(food, null),
    );
    if (portion == null || !mounted) return;
    setState(() {
      if (index == null) {
        _items.add(portion);
      } else {
        final old = _items[index];
        _items[index] = FoodSelection(
          portion.food,
          portion.amount,
          portion.unit,
          estimated: old.estimated || portion.estimated,
          origin: old.origin?.method == 'ingredient_estimate'
              ? old.origin!.adjusted()
              : FoodOrigin(
                  method: 'manual',
                  quantityBasis: 'user_entered',
                  recognizedName: old.origin?.recognizedName,
                ),
        );
      }
      _preview = null;
      _invalid.clear();
    });
  }

  void _recordRemovedIngredient(FoodSelection removed) {
    if (_analysisContext == null) return;
    final origin = removed.origin;
    if (origin?.method != 'ingredient_estimate' ||
        origin?.recognizedName == null ||
        origin?.ingredientName == null) {
      return;
    }
    final dish = origin!.recognizedName!;
    final groupRemains = _items.any(
      (item) =>
          item.origin?.method == 'ingredient_estimate' &&
          item.origin?.recognizedName == dish,
    );
    final omitted = _analysisContext!.excluded
        .where((item) => groupRemains || item.dishName != dish)
        .toList();
    if (groupRemains &&
        !omitted.any(
          (item) => item.dishName == dish && item.name == origin.ingredientName,
        )) {
      omitted.add(
        ExcludedIngredient(dish, origin.ingredientName!, 'user_excluded'),
      );
    }
    _analysisContext = AnalysisContext(omitted);
  }

  Future<void> _amount(int index) async {
    final portion = await showDialog<FoodSelection>(
      context: context,
      builder: (_) => _PortionDialog(_items[index].food, _items[index]),
    );
    if (portion != null && mounted) {
      setState(() {
        _items[index] = portion;
        _preview = null;
        _invalid.clear();
      });
    }
  }

  Future<void> _chooseTime() async {
    final wall = koreanTime(_time);
    final day = await showDatePicker(
      context: context,
      initialDate: wall,
      firstDate: DateTime(wall.year < 2000 ? wall.year : 2000),
      lastDate: DateTime(wall.year > 2100 ? wall.year : 2100, 12, 31),
    );
    if (day == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: wall.hour, minute: wall.minute),
    );
    if (time != null && mounted) {
      setState(
        () => _time = DateTime.utc(
          day.year,
          day.month,
          day.day,
          time.hour,
          time.minute,
        ).subtract(const Duration(hours: 9)),
      );
    }
  }

  void _markInvalid(ApiException error) {
    for (final field in error.fields) {
      final match = RegExp(r'^body\.items\.(\d+)\.').firstMatch(field);
      final index = match == null ? null : int.tryParse(match[1]!);
      if (index != null && index < _items.length) _invalid.add(index);
    }
  }

  Future<void> _calculate() async {
    setState(() {
      _busy = true;
      _error = null;
      _invalid.clear();
    });
    try {
      final preview = await widget.api.preview(
        _items,
        analysisContext: _analysisContext,
      );
      if (mounted) {
        setState(() {
          _preview = preview;
          _invalid.addAll(preview.invalid);
        });
      }
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _error = error.message;
          _markInvalid(error);
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    if (!_canSave) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      late SavedIntake saved;
      if (widget.existing case final original?) {
        saved = await widget.api.update(
          original,
          _time,
          items: _timeOnly ? null : _items,
          analysisContext: _analysisContext,
        );
      } else {
        final attempt =
            _pending ??
            await widget.api.prepare(
              _time,
              _items,
              analysisContext: _analysisContext,
            );
        if (!mounted) return;
        setState(() => _pending = attempt);
        saved = await widget.api.submit(attempt);
      }
      if (mounted) {
        if (_restoredBeforePhoto) {
          Navigator.pop(context);
        } else {
          Navigator.pop(context, saved);
        }
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.message;
        _markInvalid(error);
        _conflict =
            widget.existing != null && error.code == 'MEAL_VERSION_CHANGED';
      });
      if (widget.existing == null) {
        try {
          final pending = await widget.api.pending();
          if (mounted) {
            setState(() {
              _pending = pending;
              if (pending != null) {
                _items
                  ..clear()
                  ..addAll(pending.items);
                _time = pending.eatenAt;
                _preview = null;
                _invalid.clear();
              }
            });
          }
        } on ApiException {
          /* Retain the known pending request until it can be read safely. */
        }
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final editable =
        !_busy &&
        !_loading &&
        !_restoreFailed &&
        _pending == null &&
        !_conflict;
    final total =
        _preview?.total ?? (_timeOnly ? widget.existing?.total : null);
    return PopScope(
      canPop: !_busy,
      child: Scaffold(
        appBar: AppBar(
          title: Text(widget.existing == null ? '식사 기록하기' : '식사 기록 수정'),
        ),
        body: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  if (_error case final error?) ...[
                    Notice(error),
                    const SizedBox(height: 12),
                  ],
                  if (_restoreFailed)
                    OutlinedButton(
                      onPressed: _restore,
                      child: const Text('이전 저장 요청 다시 확인'),
                    ),
                  if (_restoreFailed)
                    OutlinedButton(
                      onPressed: !_busy ? _repair : null,
                      child: const Text('저장한 식사 확인 후 다시 입력'),
                    ),
                  if (_pending != null)
                    const Notice(
                      '이 식사의 저장 결과를 다시 확인해 주세요. 같은 요청으로 확인하므로 중복 저장하지 않아요.',
                    ),
                  if (_conflict)
                    FilledButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('최신 기록 확인하러 돌아가기'),
                    ),
                  OutlinedButton.icon(
                    onPressed: editable ? _chooseTime : null,
                    icon: const Icon(Icons.schedule),
                    label: Text('${_when(context, _time)}\n한국 시간 기준'),
                  ),
                  const SectionTitle('먹은 음식과 양'),
                  if (widget.initialNotice != null && !_restoredBeforePhoto)
                    Notice(widget.initialNotice!),
                  if (_pending != null && widget.initialItems.isNotEmpty)
                    const Notice(
                      '이전 식사의 저장 확인이 먼저예요. 이번 사진에서 고른 음식은 아직 반영하지 않았어요. 저장 확인 후 사진 화면에서 다시 진행해 주세요.',
                    ),
                  for (var i = 0; i < _items.length; i++)
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Text(
                              _items[i].food.name,
                              style: const TextStyle(
                                fontSize: 20,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            Text(
                              '${_items[i].amount} ${_items[i].unit}',
                              style: const TextStyle(fontSize: 18),
                            ),
                            if (_items[i].estimated)
                              const Text('예상 분량 · 실제 먹은 양과 다를 수 있어요'),
                            if (_invalid.contains(i))
                              const Notice('음식 정보와 양을 다시 확인해 주세요.'),
                            Wrap(
                              spacing: 8,
                              children: [
                                TextButton(
                                  onPressed: editable ? () => _amount(i) : null,
                                  child: const Text('양 바꾸기'),
                                ),
                                TextButton(
                                  onPressed: editable ? () => _choose(i) : null,
                                  child: const Text('음식 다시 고르기'),
                                ),
                                TextButton(
                                  onPressed: editable
                                      ? () => setState(() {
                                          final removed = _items.removeAt(i);
                                          _recordRemovedIngredient(removed);
                                          _invalid.clear();
                                          _preview = null;
                                        })
                                      : null,
                                  child: const Text('빼기'),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  if (_items.length < 30)
                    OutlinedButton.icon(
                      key: const Key('intake-add-food'),
                      onPressed: editable ? () => _choose() : null,
                      icon: const Icon(Icons.add),
                      label: const Text('먹은 음식 추가'),
                    ),
                  const SizedBox(height: 12),
                  if (_pending == null)
                    FilledButton(
                      key: const Key('intake-preview'),
                      onPressed: editable && _items.isNotEmpty
                          ? _calculate
                          : null,
                      child: Text(_busy ? '처리 중이에요' : '영양 확인하기'),
                    ),
                  if (total != null) ...[
                    const SectionTitle('확인한 영양 정보'),
                    IntakeEvidenceView(
                      items: _items,
                      contextInfo: _analysisContext,
                    ),
                    IntakeNutrientView(total),
                  ],
                  if (_preview?.notes.isNotEmpty == true)
                    ExpansionTile(
                      title: const Text('계산 근거 보기'),
                      children: [
                        for (final note in _preview!.notes)
                          Padding(
                            padding: const EdgeInsets.all(12),
                            child: Text(note),
                          ),
                      ],
                    ),
                  const SizedBox(height: 16),
                  FilledButton.icon(
                    key: const Key('intake-save'),
                    onPressed: _canSave ? _save : null,
                    icon: const Icon(Icons.check),
                    label: Text(
                      _busy
                          ? '저장 확인 중이에요'
                          : _pending != null
                          ? '저장 다시 확인'
                          : '이 식사 기록 저장',
                    ),
                  ),
                  const SizedBox(height: 12),
                  if (_error != null || _pending != null)
                    OutlinedButton(
                      onPressed: !_busy
                          ? () => Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) =>
                                    IntakeHistoryScreen(api: widget.api),
                              ),
                            )
                          : null,
                      child: const Text('저장한 식사 확인'),
                    ),
                  const Notice(
                    '선택한 음식과 양을 공공 영양 DB로 계산한 참고 정보예요. 실제 영양은 조리법과 먹은 양에 따라 달라져요.',
                  ),
                ],
              ),
      ),
    );
  }
}

class IntakeHistoryScreen extends StatefulWidget {
  const IntakeHistoryScreen({required this.api, super.key});
  final IntakeApi api;
  @override
  State<IntakeHistoryScreen> createState() => _IntakeHistoryScreenState();
}

class _IntakeHistoryScreenState extends State<IntakeHistoryScreen> {
  DateTime _day = koreanTime(DateTime.now());
  int _offset = 0;
  late Future<IntakePage> _page = widget.api.history(_day);
  void _load([int offset = 0]) => setState(() {
    _offset = offset;
    _page = widget.api.history(_day, offset: offset);
  });
  Future<void> _date() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _day,
      firstDate: DateTime(2000),
      lastDate: DateTime(2100, 12, 31),
    );
    if (date != null && mounted) {
      _day = date;
      _load();
    }
  }

  Future<void> _open(SavedIntake item) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => IntakeDetailScreen(api: widget.api, id: item.id),
      ),
    );
    if (mounted) _load(_offset);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('저장한 식사')),
    body: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: OutlinedButton.icon(
            onPressed: _date,
            icon: const Icon(Icons.calendar_month),
            label: Text('${intakeDate(_day)} · 한국 날짜'),
          ),
        ),
        Expanded(
          child: FutureBuilder<IntakePage>(
            future: _page,
            builder: (context, snapshot) => AsyncStateView(
              loading: snapshot.connectionState != ConnectionState.done,
              error: snapshot.error as ApiException?,
              onRetry: () => _load(_offset),
              isEmpty: false,
              builder: (context) {
                final page = snapshot.data!;
                return ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    if (page.total == 0) const Notice('이 날에 저장한 식사가 없어요.'),
                    for (final item in page.items)
                      FeatureTile(
                        title: _when(context, item.eatenAt),
                        subtitle:
                            '열량 ${nutrientLabel(item.total.nutrients.values['energy_kcal'], 'kcal')}${item.containsEstimates ? ' · 추정값 포함' : ''}${item.analysisContext?.partial == true ? ' · 제외 재료 있음' : ''} · 눌러서 음식과 양 확인',
                        icon: Icons.receipt_long_outlined,
                        onTap: () => _open(item),
                      ),
                    Wrap(
                      spacing: 8,
                      children: [
                        if (_offset > 0)
                          OutlinedButton(
                            onPressed: () => _load(_offset - 20),
                            child: const Text('이전 기록'),
                          ),
                        if (_offset + page.items.length < page.total)
                          OutlinedButton(
                            onPressed: () => _load(_offset + 20),
                            child: const Text('다음 기록'),
                          ),
                      ],
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ],
    ),
  );
}

class IntakeDetailScreen extends StatefulWidget {
  const IntakeDetailScreen({required this.api, required this.id, super.key});
  final IntakeApi api;
  final String id;
  @override
  State<IntakeDetailScreen> createState() => _IntakeDetailScreenState();
}

class _IntakeDetailScreenState extends State<IntakeDetailScreen> {
  late Future<SavedIntake> _meal = widget.api.detail(widget.id);
  bool _busy = false;
  void _load() => setState(() {
    _meal = widget.api.detail(widget.id);
  });
  Future<void> _edit(SavedIntake meal) async {
    await Navigator.of(context).push<SavedIntake>(
      MaterialPageRoute(
        builder: (_) => IntakeEditor(api: widget.api, existing: meal),
      ),
    );
    if (mounted) _load();
  }

  Future<void> _delete(SavedIntake meal) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('이 식사 기록을 지울까요?'),
        content: Text('${_when(context, meal.eatenAt)}에 기록한 음식과 양을 지워요.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('기록 지우기'),
          ),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await widget.api.remove(meal);
      if (mounted) Navigator.pop(context);
    } on ApiException catch (error) {
      if (mounted) {
        showMessage(context, error.message);
        if (error.statusCode == 409) _load();
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('식사 기록 상세')),
    body: FutureBuilder<SavedIntake>(
      future: _meal,
      builder: (context, snapshot) => AsyncStateView(
        loading: snapshot.connectionState != ConnectionState.done,
        error: snapshot.error as ApiException?,
        onRetry: _load,
        isEmpty: false,
        builder: (context) {
          final meal = snapshot.data!;
          return ListView(
            // Leave room to scroll actions above a temporary error SnackBar at large text.
            padding: EdgeInsets.fromLTRB(
              16,
              16,
              16,
              112 + MediaQuery.viewPaddingOf(context).bottom,
            ),
            children: [
              Text(
                '${_when(context, meal.eatenAt)} · 한국 시간',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SectionTitle('먹은 음식'),
              for (final item in meal.items)
                ListTile(
                  title: Text(item.food.name),
                  subtitle: Text(
                    '${item.amount} ${item.unit}\n원천 기준량: ${item.food.basisText ?? '확인되지 않음'}${item.food.hasServing ? '\n원천 1회 분량: ${item.food.servingReference}' : ''}',
                  ),
                ),
              const SectionTitle('저장 당시 영양'),
              IntakeEvidenceView(
                items: meal.items,
                contextInfo: meal.analysisContext,
              ),
              if (meal.items.any((item) => item.estimated))
                const Notice('예상 분량으로 계산한 식사가 포함돼 있어요. 실제 먹은 양을 측정한 값은 아니에요.'),
              IntakeNutrientView(meal.total),
              if (meal.legacy)
                const Notice('이전 기록은 당시 저장한 수치를 보여 드려요. 자세한 환산 근거는 보관되지 않았어요.'),
              FilledButton(
                onPressed: _busy ? null : () => _edit(meal),
                child: const Text('음식·양·시간 수정'),
              ),
              OutlinedButton(
                onPressed: _busy ? null : () => _delete(meal),
                child: const Text('이 식사 기록 지우기'),
              ),
            ],
          );
        },
      ),
    ),
  );
}
