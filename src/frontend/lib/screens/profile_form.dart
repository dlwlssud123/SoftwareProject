import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../data/demo_repository.dart';
import '../models/recommendations.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'recommendation_results.dart';

class ProfileForm extends StatefulWidget {
  const ProfileForm({
    required this.repository,
    required this.settings,
    this.welfare = false,
    this.initialTime = MealTime.lunch,
    super.key,
  });
  final DemoRepository repository;
  final AppSettings settings;
  final bool welfare;
  final MealTime initialTime;
  @override
  State<ProfileForm> createState() => _ProfileFormState();
}

class _ProfileFormState extends State<ProfileForm> {
  final form = GlobalKey<FormState>();
  final scroll = ScrollController();
  final name = TextEditingController();
  final age = TextEditingController();
  final district = TextEditingController();
  var region = '서울특별시';
  var gender = '여성';
  var income = '선택 안 함';
  var livesAlone = true;
  var softFood = false;
  var consent = false;
  var step = 0;
  var loading = false;
  final conditions = <String>{};
  final allergies = <String>{};
  late MealTime time = widget.initialTime;
  static const regions = [
    '서울특별시',
    '부산광역시',
    '대구광역시',
    '인천광역시',
    '광주광역시',
    '대전광역시',
    '울산광역시',
    '세종특별자치시',
    '경기도',
    '강원특별자치도',
    '충청북도',
    '충청남도',
    '전북특별자치도',
    '전라남도',
    '경상북도',
    '경상남도',
    '제주특별자치도',
  ];

  @override
  void dispose() {
    name.dispose();
    age.dispose();
    district.dispose();
    scroll.dispose();
    super.dispose();
  }

  void fillExample() {
    setState(() {
      name.text = '김영희';
      age.text = '72';
      district.text = '노원구';
      region = '서울특별시';
      gender = '여성';
      livesAlone = true;
      income = '중위소득 50% 이하';
      conditions
        ..clear()
        ..add('고혈압');
      allergies.clear();
      softFood = false;
    });
  }

  Future<void> next() async {
    FocusScope.of(context).unfocus();
    if (step == 0) {
      if (!form.currentState!.validate()) return;
      setState(() => step = 1);
      scroll.jumpTo(0);
      return;
    }
    if (!consent) {
      showMessage(context, '정보 이용 안내를 확인해 주세요.');
      return;
    }
    setState(() => loading = true);
    // Keep the loading state short and deterministic for offline presentations.
    await Future<void>.delayed(const Duration(milliseconds: 500));
    if (!mounted) return;
    final profile = UserProfile(
      name: name.text,
      age: int.parse(age.text),
      gender: gender,
      region: region,
      district: district.text.trim(),
      livesAlone: livesAlone,
      income: income,
      conditions: Set.of(conditions),
      allergies: Set.of(allergies),
      softFood: softFood,
    );
    setState(() => loading = false);
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => RecommendationResults(
          repository: widget.repository,
          settings: widget.settings,
          profile: profile,
          time: time,
          welfare: widget.welfare,
        ),
      ),
    );
  }

  Widget selection(String title, List<String> values, Set<String> selected) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 22),
          Text(title, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: values
                .map(
                  (value) => FilterChip(
                    label: Text(value),
                    selected: selected.contains(value),
                    onSelected: (on) => setState(() {
                      if (on) {
                        selected.add(value);
                      } else {
                        selected.remove(value);
                      }
                    }),
                    selectedColor: const Color(0xFFDFEDDB),
                    padding: const EdgeInsets.all(8),
                    side: const BorderSide(color: line),
                  ),
                )
                .toList(),
          ),
        ],
      );

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(widget.welfare ? '맞춤 복지 추천' : '맞춤 식단 추천')),
    body: Form(
      key: form,
      child: ListView(
        key: const Key('profile-scroll'),
        controller: scroll,
        padding: const EdgeInsets.fromLTRB(22, 12, 22, 28),
        children: [
          Row(
            children: [
              Tag('${step + 1} / 2단계'),
              const Spacer(),
              TextButton.icon(
                key: const Key('sample-fill'),
                onPressed: fillExample,
                icon: const Icon(Icons.auto_fix_high_rounded, size: 18),
                label: const Text('예시 정보 채우기'),
              ),
            ],
          ),
          const SizedBox(height: 12),
          LinearProgressIndicator(
            value: (step + 1) / 2,
            minHeight: 5,
            borderRadius: BorderRadius.circular(4),
            backgroundColor: line,
            color: blue,
          ),
          const SizedBox(height: 25),
          Text(
            step == 0
                ? '기본 정보를 입력해 주세요'
                : widget.welfare
                ? '생활 조건을 선택해 주세요'
                : '식사 조건을 선택해 주세요',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 10),
          Text(
            step == 0 ? '입력 정보에 맞춰 추천해 드려요.' : '선택한 조건을 추천 결과에 반영할게요.',
            style: const TextStyle(fontSize: 16, color: muted),
          ),
          const SizedBox(height: 25),
          if (step == 0) ...[
            TextFormField(
              key: const Key('profile-name'),
              controller: name,
              maxLength: 20,
              decoration: const InputDecoration(
                labelText: '이름 또는 별명 (선택)',
                hintText: '어떻게 불러 드릴까요?',
                counterText: '',
              ),
            ),
            const SizedBox(height: 16),
            TextFormField(
              key: const Key('profile-age'),
              controller: age,
              keyboardType: TextInputType.number,
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
                LengthLimitingTextInputFormatter(3),
              ],
              decoration: const InputDecoration(
                labelText: '나이',
                suffixText: '세',
              ),
              validator: (value) {
                final n = int.tryParse(value ?? '');
                return n == null || n < 20 || n > 120
                    ? '나이를 20~120세 사이로 입력해 주세요.'
                    : null;
              },
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              key: ValueKey('gender-$gender'),
              initialValue: gender,
              decoration: const InputDecoration(labelText: '성별'),
              items: [
                '여성',
                '남성',
                '선택 안 함',
              ].map((v) => DropdownMenuItem(value: v, child: Text(v))).toList(),
              onChanged: (v) => setState(() => gender = v!),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              key: ValueKey('region-$region'),
              initialValue: region,
              isExpanded: true,
              decoration: const InputDecoration(labelText: '거주 지역'),
              items: regions
                  .map((v) => DropdownMenuItem(value: v, child: Text(v)))
                  .toList(),
              onChanged: (v) => setState(() {
                region = v!;
                district.clear();
              }),
            ),
            const SizedBox(height: 16),
            TextFormField(
              key: const Key('profile-district'),
              controller: district,
              maxLength: 30,
              decoration: const InputDecoration(
                labelText: '시·군·구',
                hintText: '예: 노원구',
                counterText: '',
              ),
              validator: (v) =>
                  v == null || v.trim().isEmpty ? '거주하는 시·군·구를 입력해 주세요.' : null,
            ),
          ] else ...[
            Notice(
              '${name.text.trim().isEmpty ? '어르신' : name.text.trim()} · ${age.text}세 · $region ${district.text}',
              icon: Icons.person_outline_rounded,
            ),
            if (widget.welfare) ...[
              const SectionTitle('가구 형태'),
              Wrap(
                spacing: 10,
                runSpacing: 8,
                children: [
                  for (final alone in [true, false])
                    ChoiceChip(
                      label: Text(alone ? '혼자 살아요' : '함께 살아요'),
                      selected: livesAlone == alone,
                      onSelected: (_) => setState(() => livesAlone = alone),
                      padding: const EdgeInsets.all(10),
                    ),
                ],
              ),
              const SectionTitle('소득 구간'),
              DropdownButtonFormField<String>(
                key: ValueKey(income),
                initialValue: income,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: '알고 계신 구간을 선택해 주세요',
                ),
                items: ['선택 안 함', '중위소득 50% 이하', '중위소득 50% 초과', '잘 모르겠어요']
                    .map((v) => DropdownMenuItem(value: v, child: Text(v)))
                    .toList(),
                onChanged: (v) => setState(() => income = v!),
              ),
              const SizedBox(height: 20),
              const Notice(
                '전국 복지 사업을 안내해요. 실제 지원 여부는 각 사업의 선정기준과 담당 기관에서 확인해 주세요.',
              ),
            ] else ...[
              const SectionTitle('식사 시간'),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: MealTime.values
                    .map(
                      (v) => ChoiceChip(
                        label: Text(v.label),
                        selected: time == v,
                        onSelected: (_) => setState(() => time = v),
                        padding: const EdgeInsets.all(10),
                      ),
                    )
                    .toList(),
              ),
              selection('건강 상태 (선택)', ['고혈압', '당뇨'], conditions),
              selection('피해야 할 알레르기 재료 (선택)', [
                '달걀',
                '우유',
                '대두',
                '새우',
                '밀',
                '땅콩',
              ], allergies),
              const SizedBox(height: 16),
              SwitchListTile.adaptive(
                contentPadding: EdgeInsets.zero,
                title: const Text(
                  '부드러운 음식이 좋아요',
                  style: TextStyle(fontSize: 17),
                ),
                value: softFood,
                onChanged: (v) => setState(() => softFood = v),
              ),
            ],
            const SizedBox(height: 20),
            CheckboxListTile(
              key: const Key('profile-consent'),
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: const Text(
                '이번 추천에 입력 정보를 사용하는 것을 확인했어요.',
                style: TextStyle(fontSize: 16),
              ),
              subtitle: const Text(
                '발표 모드에서는 외부로 전송하거나 저장하지 않아요.',
                style: TextStyle(fontSize: 13),
              ),
              value: consent,
              onChanged: (v) => setState(() => consent = v ?? false),
            ),
          ],
        ],
      ),
    ),
    bottomNavigationBar: SafeArea(
      top: false,
      child: Container(
        color: canvas,
        padding: const EdgeInsets.fromLTRB(22, 10, 22, 12),
        child: Row(
          children: [
            if (step == 1) ...[
              IconButton(
                tooltip: '기본 정보 수정',
                onPressed: loading
                    ? null
                    : () {
                        setState(() => step = 0);
                        scroll.jumpTo(0);
                      },
                icon: const Icon(Icons.arrow_back_rounded),
              ),
              const SizedBox(width: 8),
            ],
            Expanded(
              child: FilledButton(
                key: Key(step == 0 ? 'profile-next' : 'recommend-submit'),
                onPressed: loading ? null : next,
                child: loading
                    ? const SizedBox(
                        width: 24,
                        height: 24,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Text(
                        step == 0
                            ? '다음으로'
                            : widget.welfare
                            ? '맞춤 복지 서비스 찾기'
                            : '맞춤 레시피 추천받기',
                      ),
              ),
            ),
          ],
        ),
      ),
    ),
  );
}
