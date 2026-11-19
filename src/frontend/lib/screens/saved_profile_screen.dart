import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/network/api_exception.dart';
import '../data/profile_api.dart';
import '../services/account.dart';
import '../theme.dart';
import '../widgets/async_state_view.dart';
import '../widgets/common.dart';

class SavedProfileScreen extends StatefulWidget {
  const SavedProfileScreen({
    required this.account,
    required this.token,
    super.key,
  });

  final Account account;
  final String token;

  @override
  State<SavedProfileScreen> createState() => _SavedProfileScreenState();
}

class _SavedProfileScreenState extends State<SavedProfileScreen> {
  static const allergens = [
    '알류',
    '우유',
    '메밀',
    '땅콩',
    '대두',
    '밀',
    '고등어',
    '게',
    '새우',
    '돼지고기',
    '복숭아',
    '토마토',
    '아황산류',
    '호두',
    '닭고기',
    '쇠고기',
    '오징어',
    '조개류',
    '잣',
  ];

  final _form = GlobalKey<FormState>();
  final _age = TextEditingController();
  final _region = TextEditingController();
  final _district = TextEditingController();
  final _preferred = TextEditingController();
  final _excluded = TextEditingController();
  final _allergens = <String>{};
  ProfilePreferences? _saved;
  bool? _livesAlone, _softFood;
  bool _consent = false;
  bool _loading = true;
  bool _writing = false;
  ApiException? _loadError;
  String? _message;

  ProfileApi get _api => widget.account.profiles;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final controller in [
      _age,
      _region,
      _district,
      _preferred,
      _excluded,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  void _showProfile(ProfilePreferences? profile) {
    _saved = profile;
    _age.text = profile?.age?.toString() ?? '';
    _region.text = profile?.region ?? '';
    _district.text = profile?.district ?? '';
    _preferred.text = profile?.preferredIngredients.join('\n') ?? '';
    _excluded.text = profile?.excludedIngredients.join('\n') ?? '';
    _livesAlone = profile?.livesAlone;
    _softFood = profile?.softFood;
    _allergens
      ..clear()
      ..addAll(profile?.excludeAllergens ?? const []);
    _consent = false;
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final profile = await _api.load(widget.token);
      if (mounted) setState(() => _showProfile(profile));
    } on ApiException catch (error) {
      if (mounted) setState(() => _loadError = error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    if (_writing || !_form.currentState!.validate()) return;
    final giveConsent = _saved == null;
    if (giveConsent && !_consent) {
      setState(() => _message = '서버 저장에 동의해 주세요.');
      return;
    }
    final preferences = ProfilePreferences(
      age: int.tryParse(_age.text),
      region: _optionalText(_region.text),
      district: _optionalText(_district.text),
      livesAlone: _livesAlone,
      softFood: _softFood,
      preferredIngredients: _ingredients(
        _preferred.text,
        _saved?.preferredIngredients,
      ),
      excludedIngredients: _ingredients(
        _excluded.text,
        _saved?.excludedIngredients,
      ),
      excludeAllergens: _allergens.toList(),
    );
    FocusScope.of(context).unfocus();
    await _write(
      () => _api.save(widget.token, preferences, previous: _saved),
      '추천 조건을 저장했어요.',
    );
  }

  Future<void> _withdraw() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('프로필 저장 동의를 철회할까요?'),
        content: const Text('서버에 저장된 추천 조건을 삭제해요.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('철회하고 삭제'),
          ),
        ],
      ),
    );
    if (!mounted || confirmed != true || _writing) return;
    await _write(() async {
      await _api.withdraw(widget.token);
      return null;
    }, '동의를 철회하고 서버 프로필을 삭제했어요.');
  }

  Future<void> _write(
    Future<ProfilePreferences?> Function() action,
    String success,
  ) async {
    setState(() {
      _writing = true;
      _message = null;
    });
    try {
      final profile = await action();
      if (!mounted) return;
      setState(() {
        _showProfile(profile);
        _message = success;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        // Another device may have withdrawn consent since this form was loaded.
        if (error.statusCode == 409) {
          _saved = null;
          _consent = false;
        }
        _message = error.message;
      });
    } finally {
      if (mounted) setState(() => _writing = false);
    }
  }

  String? _optionalText(String text) =>
      text.trim().isEmpty ? null : text.trim();

  List<String> _ingredients(String text, List<String>? previous) {
    if (previous != null && text == previous.join('\n')) return previous;
    return text
        .split('\n')
        .map((line) => line.trim())
        .where((line) => line.isNotEmpty)
        .toList();
  }

  Widget _ingredientField(
    String label,
    TextEditingController controller,
    List<String>? previous,
  ) => TextFormField(
    controller: controller,
    enabled: !_writing,
    minLines: 2,
    maxLines: 4,
    decoration: InputDecoration(
      labelText: label,
      helperText: '한 줄에 한 가지씩 입력해 주세요.',
    ),
    validator: (text) {
      final values = _ingredients(text ?? '', previous);
      if (values.length > 30) return '재료는 30개까지 입력해 주세요.';
      if (values.any((value) => value.runes.length > 100)) {
        return '재료 하나는 100자까지 입력해 주세요.';
      }
      return null;
    },
  );

  Widget _choice(
    String label,
    bool? value,
    String yes,
    String no,
    ValueChanged<bool?> onChanged,
  ) => InputDecorator(
    decoration: InputDecoration(labelText: label),
    child: DropdownButtonHideUnderline(
      child: DropdownButton<bool>(
        value: value,
        isDense: true,
        isExpanded: true,
        items: [
          const DropdownMenuItem<bool>(child: Text('선택 안 함')),
          DropdownMenuItem(value: true, child: Text(yes)),
          DropdownMenuItem(value: false, child: Text(no)),
        ],
        onChanged: _writing ? null : onChanged,
      ),
    ),
  );

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('추천 조건 관리')),
    body: AsyncStateView(
      loading: _loading,
      isEmpty: false,
      error: _loadError,
      onRetry: _load,
      builder: (_) => Form(
        key: _form,
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Notice(
                '나이·거주 지역·가구 형태와 음식 조건을 추천에 쓰기 위해 서버에 저장할 수 있어요. 저장 동의를 철회하면 서버에서 프로필을 삭제해요.',
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _age,
                enabled: !_writing,
                keyboardType: TextInputType.number,
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(3),
                ],
                decoration: const InputDecoration(
                  labelText: '나이 (선택)',
                  suffixText: '세',
                ),
                validator: (value) {
                  if (value == null || value.isEmpty) return null;
                  final age = int.tryParse(value);
                  return age == null || age > 120
                      ? '나이는 0~120세로 입력해 주세요.'
                      : null;
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _region,
                enabled: !_writing,
                maxLength: 100,
                decoration: const InputDecoration(
                  labelText: '시·도 (선택)',
                  counterText: '',
                ),
                validator: _validateRegion,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _district,
                enabled: !_writing,
                maxLength: 100,
                decoration: const InputDecoration(
                  labelText: '시·군·구 (선택)',
                  counterText: '',
                ),
                validator: _validateRegion,
              ),
              const SizedBox(height: 12),
              _choice(
                '가구 형태',
                _livesAlone,
                '혼자 살아요',
                '함께 살아요',
                (value) => setState(() => _livesAlone = value),
              ),
              const SizedBox(height: 12),
              _choice(
                '부드러운 음식 선호',
                _softFood,
                '선호해요',
                '선호하지 않아요',
                (value) => setState(() => _softFood = value),
              ),
              const SizedBox(height: 12),
              _ingredientField(
                '좋아하는 재료 (선택)',
                _preferred,
                _saved?.preferredIngredients,
              ),
              const SizedBox(height: 12),
              _ingredientField(
                '피하고 싶은 재료 (선택)',
                _excluded,
                _saved?.excludedIngredients,
              ),
              const SectionTitle('알레르기 재료 (선택)'),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  for (final allergen in allergens)
                    FilterChip(
                      label: Text(allergen == '알류' ? '달걀' : allergen),
                      selected: _allergens.contains(allergen),
                      onSelected: _writing
                          ? null
                          : (selected) {
                              setState(() {
                                if (selected) {
                                  _allergens.add(allergen);
                                } else {
                                  _allergens.remove(allergen);
                                }
                              });
                            },
                    ),
                ],
              ),
              const SizedBox(height: 16),
              if (_saved == null)
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text('추천 조건을 서버에 저장하는 데 동의해요.'),
                  value: _consent,
                  onChanged: _writing
                      ? null
                      : (value) => setState(() => _consent = value ?? false),
                ),
              const SizedBox(height: 8),
              if (_message case final message?) ...[
                Semantics(
                  liveRegion: true,
                  child: Notice(message, color: muted),
                ),
                const SizedBox(height: 8),
              ],
              if (_writing)
                const LinearProgressIndicator(semanticsLabel: '프로필 처리 중'),
              FilledButton(
                onPressed: _writing ? null : _save,
                child: const Text('추천 조건 저장'),
              ),
              if (_saved != null) ...[
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed: _writing ? null : _withdraw,
                  child: const Text('저장 동의 철회'),
                ),
              ],
            ],
          ),
        ),
      ),
    ),
  );

  String? _validateRegion(String? value) =>
      (value ?? '').trim().runes.length > 100 ? '100자까지 입력해 주세요.' : null;
}
