import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/network/api_exception.dart';
import '../data/welfare_api.dart';
import '../models/welfare.dart';
import '../widgets/common.dart';

const _eligibility =
    '확인해 볼 만한 복지 사업이에요. 지원 자격과 신청 가능 여부는 공식 안내나 문의처에서 확인해 주세요.';

class WelfareSearchScreen extends StatefulWidget {
  const WelfareSearchScreen({required this.api, super.key});
  final WelfareApi api;
  @override
  State<WelfareSearchScreen> createState() => _WelfareSearchScreenState();
}

class _WelfareSearchScreenState extends State<WelfareSearchScreen> {
  final _form = GlobalKey<FormState>();
  final _age = TextEditingController();
  final _district = TextEditingController();
  String _region = '서울특별시';
  bool? _alone;
  static const _regions = [
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
    _age.dispose();
    _district.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('복지 찾기')),
    body: Form(
      key: _form,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 100),
        children: [
          OutlinedButton.icon(
            key: const Key('saved-welfare'),
            icon: const Icon(Icons.bookmark_outline),
            label: const Text('저장한 복지 · 내 메모'),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => SavedWelfareScreen(api: widget.api),
              ),
            ),
          ),
          const SectionTitle('내게 필요한 복지 찾아보기'),
          const Notice('이름·소득·건강 정보는 입력하지 않아요. 아래 조건은 이번 검색에만 쓰고 저장하지 않아요.'),
          const SizedBox(height: 20),
          TextFormField(
            key: const Key('welfare-age'),
            controller: _age,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            maxLength: 3,
            decoration: const InputDecoration(
              labelText: '만 나이',
              hintText: '예: 70',
            ),
            validator: (text) {
              final value = int.tryParse(text ?? '');
              return value == null || value < 0 || value > 120
                  ? '만 나이를 0~120 사이로 입력해 주세요.'
                  : null;
            },
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _region,
            isExpanded: true,
            decoration: const InputDecoration(labelText: '거주 시·도'),
            items: [
              for (final region in _regions)
                DropdownMenuItem(value: region, child: Text(region)),
            ],
            onChanged: (value) => setState(() {
              _region = value!;
              _district.clear();
            }),
          ),
          const SizedBox(height: 20),
          TextFormField(
            key: const Key('welfare-district'),
            controller: _district,
            maxLength: 50,
            decoration: const InputDecoration(
              labelText: '시·군·구 (선택)',
              hintText: '예: 강남구',
            ),
          ),
          const SectionTitle('혼자 살고 계신가요? (선택)'),
          Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              for (final choice in [
                (null, '선택 안 함'),
                (true, '예'),
                (false, '아니요'),
              ])
                ChoiceChip(
                  label: Text(choice.$2),
                  selected: _alone == choice.$1,
                  onSelected: (_) => setState(() => _alone = choice.$1),
                ),
            ],
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            key: const Key('find-welfare'),
            icon: const Icon(Icons.search),
            label: const Text('복지 찾아보기'),
            onPressed: () {
              if (!_form.currentState!.validate()) return;
              FocusScope.of(context).unfocus();
              final age = int.parse(_age.text);
              final region = _region;
              final district = _district.text;
              final alone = _alone;
              Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => _WelfareResultsScreen(
                    api: widget.api,
                    search: () => widget.api.recommend(
                      age: age,
                      region: region,
                      district: district,
                      livesAlone: alone,
                    ),
                  ),
                ),
              );
            },
          ),
        ],
      ),
    ),
  );
}

class _WelfareResultsScreen extends StatefulWidget {
  const _WelfareResultsScreen({required this.api, required this.search});
  final WelfareApi api;
  final Future<WelfareResults> Function() search;
  @override
  State<_WelfareResultsScreen> createState() => _WelfareResultsScreenState();
}

class _WelfareResultsScreenState extends State<_WelfareResultsScreen> {
  late Future<WelfareResults> _result = widget.search();
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('확인해 볼 복지')),
    body: _WelfareFuture<WelfareResults>(
      future: _result,
      retry: () => setState(() {
        _result = widget.search();
      }),
      builder: (data) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          for (final warning in data.warnings) ...[
            Notice(warning),
            const SizedBox(height: 12),
          ],
          if (data.items.isEmpty)
            const Notice(
              '검색된 복지 정보가 없어요. 이전 화면에서 지역을 확인하거나 시·군·구를 비우고 다시 찾아보세요.',
            ),
          for (final match in data.items)
            Card(
              child: ListTile(
                contentPadding: const EdgeInsets.all(16),
                title: Text(
                  match.service.title,
                  style: const TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                subtitle: Text(
                  [
                    match.service.region.isEmpty ? '전국' : match.service.region,
                    match.service.summary,
                    ...match.reasons,
                  ].where((s) => s.isNotEmpty).join('\n\n'),
                  style: const TextStyle(fontSize: 18, height: 1.5),
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => WelfareDetailScreen(
                      api: widget.api,
                      id: match.service.id,
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    ),
  );
}

class SavedWelfareScreen extends StatefulWidget {
  const SavedWelfareScreen({required this.api, super.key});
  final WelfareApi api;
  @override
  State<SavedWelfareScreen> createState() => _SavedWelfareScreenState();
}

class _SavedWelfareScreenState extends State<SavedWelfareScreen> {
  int _offset = 0;
  late Future<SavedWelfarePage> _list = widget.api.saved();
  void _load() => setState(() {
    _list = widget.api.saved(offset: _offset);
  });

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('저장한 복지')),
    body: _WelfareFuture<SavedWelfarePage>(
      future: _list,
      retry: _load,
      builder: (data) => ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 100),
        children: [
          const Notice('메모는 본인 계정에 저장돼요. 실제 신청·심사 상태와는 별개예요.'),
          if (data.items.isEmpty)
            const Padding(
              padding: EdgeInsets.all(20),
              child: Text('이 페이지에 저장한 복지가 없어요. 복지 상세에서 관심 저장을 눌러 주세요.'),
            ),
          for (final item in data.items)
            Card(
              child: ListTile(
                title: Text(
                  item.title ?? '현재 안내를 확인할 수 없는 복지',
                  style: const TextStyle(fontSize: 20),
                ),
                subtitle: Text(
                  item.title == null
                      ? '${item.id} · 메모 확인 / 저장 해제'
                      : '상세 안내와 내 메모 보기',
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () async {
                  await Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) =>
                          WelfareDetailScreen(api: widget.api, id: item.id),
                    ),
                  );
                  if (mounted) _load();
                },
              ),
            ),
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            spacing: 12,
            children: [
              OutlinedButton(
                onPressed: _offset > 0
                    ? () {
                        _offset -= 20;
                        _load();
                      }
                    : null,
                child: const Text('이전 페이지'),
              ),
              OutlinedButton(
                onPressed: _offset + 20 < data.total
                    ? () {
                        _offset += 20;
                        _load();
                      }
                    : null,
                child: const Text('다음 페이지'),
              ),
            ],
          ),
        ],
      ),
    ),
  );
}

class WelfareDetailScreen extends StatefulWidget {
  const WelfareDetailScreen({required this.api, required this.id, super.key});
  final WelfareApi api;
  final String id;
  @override
  State<WelfareDetailScreen> createState() => _WelfareDetailScreenState();
}

class _WelfareDetailScreenState extends State<WelfareDetailScreen> {
  late Future<WelfareService> _detail = widget.api.detail(widget.id);
  late Future<bool> _saved = widget.api.isSaved(widget.id);
  bool _busy = false;
  void _loadSaved() => setState(() {
    _saved = widget.api.isSaved(widget.id);
  });

  Future<void> _toggle(bool saved) async {
    if (_busy) return;
    if (saved) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('관심 저장을 해제할까요?'),
          content: const Text('이 복지에 남긴 내 메모도 함께 삭제돼요.'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('유지하기'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('저장 해제'),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted || _busy) return;
    }
    setState(() => _busy = true);
    try {
      if (saved) {
        await widget.api.remove(widget.id);
      } else {
        await widget.api.save(widget.id);
      }
      if (mounted) {
        setState(() {
          _saved = Future.value(!saved);
        });
      }
    } on ApiException catch (error) {
      if (mounted) {
        showMessage(context, error.message);
        _loadSaved();
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('복지 상세')),
    body: ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 112),
      children: [
        const Notice(_eligibility),
        const SizedBox(height: 16),
        _WelfareFuture<WelfareService>(
          future: _detail,
          retry: () => setState(() {
            _detail = widget.api.detail(widget.id);
          }),
          notFound: const Notice(
            '이 복지의 현재 안내를 확인할 수 없어요. 이전에 저장한 메모는 아래에서 확인하거나 저장을 해제할 수 있어요.',
          ),
          builder: (service) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                service.title,
                style: const TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 12),
              Text(
                service.summary,
                style: const TextStyle(fontSize: 19, height: 1.6),
              ),
              if (service.flagged)
                const Notice('원천 자료에 확인이 필요한 항목이 있어요. 공식 안내를 함께 확인해 주세요.'),
              for (final section in [
                ('지원 대상', service.target),
                ('선정 기준', service.selection),
                ('지원 내용', service.benefit),
                ('신청 방법', service.applications.join('\n\n')),
                ('문의처', service.contacts.join('\n\n')),
              ]) ...[
                SectionTitle(section.$1),
                SelectableText(
                  section.$2.trim().isEmpty
                      ? '자료에 안내가 없어요. 공식 문의처에서 확인해 주세요.'
                      : section.$2,
                  style: const TextStyle(fontSize: 18, height: 1.6),
                ),
              ],
              const SizedBox(height: 20),
              Text(
                '자료 확인: ${welfareDate(service.checkedAt)}',
                style: const TextStyle(fontSize: 16),
              ),
              if (service.officialUrl case final url?)
                OutlinedButton.icon(
                  onPressed: () => openLink(context, url),
                  icon: const Icon(Icons.open_in_new),
                  label: const Text('공식 안내 열기'),
                )
              else
                const Notice('공식 연결 주소를 확인할 수 없어요. 위 문의처를 이용해 주세요.'),
            ],
          ),
        ),
        const SectionTitle('관심 복지와 내 메모'),
        _WelfareFuture<bool>(
          future: _saved,
          retry: _loadSaved,
          builder: (saved) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              FilledButton.icon(
                key: const Key('welfare-save'),
                onPressed: _busy ? null : () => _toggle(saved),
                icon: Icon(saved ? Icons.bookmark : Icons.bookmark_outline),
                label: Text(
                  _busy
                      ? '처리 중이에요'
                      : saved
                      ? '관심 저장 해제'
                      : '관심 저장',
                ),
              ),
              if (saved)
                OutlinedButton.icon(
                  key: const Key('welfare-note'),
                  onPressed: _busy
                      ? null
                      : () async {
                          await Navigator.of(context).push(
                            MaterialPageRoute<void>(
                              builder: (_) => WelfareNoteScreen(
                                api: widget.api,
                                id: widget.id,
                              ),
                            ),
                          );
                          if (mounted) _loadSaved();
                        },
                  icon: const Icon(Icons.edit_note),
                  label: const Text('내 진행 메모 보기 · 수정'),
                ),
              const SizedBox(height: 12),
              const Notice(
                '관심 저장은 신청이 아니에요. 메모에 주민등록번호·계좌번호 등 민감한 정보는 적지 마세요.',
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class WelfareNoteScreen extends StatefulWidget {
  const WelfareNoteScreen({required this.api, required this.id, super.key});
  final WelfareApi api;
  final String id;
  @override
  State<WelfareNoteScreen> createState() => _WelfareNoteScreenState();
}

class _WelfareNoteScreenState extends State<WelfareNoteScreen> {
  final _text = TextEditingController();
  late Future<WelfareNote> _note = _load();
  bool _busy = false;
  bool _changed = false;
  Future<WelfareNote> _load() async {
    final note = await widget.api.note(widget.id);
    if (mounted) {
      _text.text = note.text ?? '';
      _changed = false;
    }
    return note;
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final note = await widget.api.updateNote(widget.id, _text.text);
      if (!mounted) return;
      setState(() {
        _text.text = note.text ?? '';
        _changed = false;
        _note = Future.value(note);
      });
      showMessage(context, '내 메모를 저장했어요.');
    } on ApiException catch (error) {
      if (mounted) {
        showMessage(context, '${error.message}\n작성 중인 내용은 이 화면에 남아 있어요.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _leave() async {
    if (_busy) return;
    if (_changed) {
      final discard = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('수정한 메모를 저장하지 않고 나갈까요?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('계속 작성'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('나가기'),
            ),
          ],
        ),
      );
      if (discard != true || !mounted) return;
    }
    if (mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !_busy && !_changed,
    onPopInvokedWithResult: (didPop, _) {
      if (!didPop) _leave();
    },
    child: Scaffold(
      appBar: AppBar(title: const Text('내 진행 메모')),
      body: _WelfareFuture<WelfareNote>(
        future: _note,
        retry: () => setState(() {
          _note = _load();
        }),
        builder: (note) => ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 112),
          children: [
            const Notice(
              '예: 주민센터에 문의함, 준비할 서류 확인하기\n본인만 보는 메모이며 공식 신청·심사 상태가 아니에요.',
            ),
            const SizedBox(height: 20),
            TextField(
              key: const Key('welfare-note-input'),
              controller: _text,
              enabled: !_busy,
              minLines: 5,
              maxLines: 12,
              maxLength: 2000,
              decoration: const InputDecoration(
                labelText: '내 메모',
                alignLabelWithHint: true,
              ),
              onChanged: (_) => setState(() => _changed = true),
            ),
            if (note.updatedAt case final time?)
              Text('저장일: ${welfareDate(time)}'),
            const SizedBox(height: 20),
            FilledButton(
              key: const Key('save-welfare-note'),
              onPressed: _busy || !_changed ? null : _save,
              child: Text(_busy ? '저장 중이에요' : '메모 저장'),
            ),
            const SizedBox(height: 12),
            const Text('내용을 모두 지우고 저장하면 기존 메모도 지워져요.'),
          ],
        ),
      ),
    ),
  );
}

class _WelfareFuture<T> extends StatelessWidget {
  const _WelfareFuture({
    required this.future,
    required this.retry,
    required this.builder,
    this.notFound,
  });
  final Future<T> future;
  final VoidCallback retry;
  final Widget Function(T) builder;
  final Widget? notFound;

  @override
  Widget build(BuildContext context) => FutureBuilder<T>(
    future: future,
    builder: (context, snapshot) {
      if (snapshot.connectionState != ConnectionState.done) {
        return const Padding(
          padding: EdgeInsets.all(24),
          child: Center(child: CircularProgressIndicator()),
        );
      }
      if (snapshot.hasError) {
        final error = snapshot.error;
        if (error is ApiException &&
            error.statusCode == 404 &&
            notFound != null) {
          return notFound!;
        }
        return ListView(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            Notice(
              error is ApiException
                  ? error.message
                  : '정보를 불러오지 못했어요. 다시 시도해 주세요.',
            ),
            if (error is! ApiException || error.statusCode != 401)
              OutlinedButton(onPressed: retry, child: const Text('다시 불러오기')),
          ],
        );
      }
      return builder(snapshot.data as T);
    },
  );
}
