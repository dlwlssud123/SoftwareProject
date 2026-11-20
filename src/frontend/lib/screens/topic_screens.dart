import 'package:flutter/material.dart';

import '../core/network/api_exception.dart';
import '../data/topic_api.dart';
import '../models/topic_request.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/common.dart';

String _error(Object error) =>
    error is ApiException ? error.message : '처리하지 못했어요. 다시 시도해 주세요.';
String _date(DateTime instant) {
  final time = instant.toUtc().add(const Duration(hours: 9));
  return '${time.year}.${time.month}.${time.day}';
}

Future<bool> _confirm(
  BuildContext context,
  String title,
  String text,
  String action,
) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(text),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('아니요'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(action),
          ),
        ],
      ),
    ) ??
    false;

class TopicRequestsScreen extends StatefulWidget {
  const TopicRequestsScreen({
    required this.api,
    required this.settings,
    this.initialKind = TopicKind.lifeGuide,
    super.key,
  });
  final TopicApi api;
  final AppSettings settings;
  final TopicKind initialKind;
  @override
  State<TopicRequestsScreen> createState() => _TopicRequestsScreenState();
}

class _TopicRequestsScreenState extends State<TopicRequestsScreen> {
  final _form = GlobalKey<FormState>();
  final _text = TextEditingController();
  final _scroll = ScrollController();
  late TopicKind _kind = widget.initialKind;
  late final String? _owner = widget.api.owner;
  PendingTopic? _pending;
  bool _recoverPending = false;
  TopicPage<TopicRecord>? _history;
  bool _loading = true,
      _busy = false,
      _storageBroken = false,
      _allowPop = false,
      _lost = false;
  int _generation = 0;
  String? _message, _historyError;
  @override
  void initState() {
    super.initState();
    widget.api.identity.addListener(_identity);
    _load();
  }

  void _identity() {
    if (!mounted || _lost || widget.api.owner == _owner) return;
    _generation++;
    _text.clear();
    setState(() {
      _lost = true;
      _pending = null;
      _history = null;
      _message = null;
      _historyError = null;
      _busy = false;
      _loading = false;
    });
  }

  bool _current(int generation) =>
      mounted &&
      !_lost &&
      generation == _generation &&
      widget.api.owner == _owner;
  @override
  void dispose() {
    widget.api.identity.removeListener(_identity);
    _generation++;
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final generation = ++_generation;
    setState(() {
      _loading = true;
      _historyError = null;
    });
    PendingTopic? pending;
    try {
      pending = await widget.api.pending();
      if (_current(generation)) {
        setState(() {
          _storageBroken = false;
          _message = null;
        });
      }
    } catch (error) {
      if (_current(generation)) {
        setState(() {
          _storageBroken = true;
          _message = _error(error);
        });
      }
    }
    if (!_current(generation)) return;
    if (pending != null) {
      setState(() {
        _pending = pending;
        _kind = pending!.kind;
        _text.text = pending.topic;
      });
      try {
        final resolved = await widget.api.lookup(pending);
        if (_current(generation) && resolved != null) {
          setState(() {
            _pending = null;
            _text.clear();
            _message = resolved.withdrawn
                ? '이전 요청은 취소됐어요.'
                : '이전 요청의 접수를 확인했어요. 아래 내역에서 볼 수 있어요.';
          });
        }
      } catch (error) {
        if (_current(generation)) setState(() => _message = _error(error));
      }
    }
    try {
      final history = await widget.api.history();
      if (_current(generation)) setState(() => _history = history);
    } catch (error) {
      if (_current(generation)) setState(() => _historyError = _error(error));
    }
    if (_current(generation)) setState(() => _loading = false);
  }

  Future<void> _historyPage(int offset) async {
    if (_busy) return;
    final generation = _generation;
    setState(() {
      _busy = true;
      _historyError = null;
    });
    try {
      final history = await widget.api.history(offset: offset);
      if (_current(generation)) setState(() => _history = history);
    } catch (error) {
      if (_current(generation)) setState(() => _historyError = _error(error));
    } finally {
      if (_current(generation)) setState(() => _busy = false);
    }
  }

  Future<void> _send({bool cancel = false, bool lookup = false}) async {
    if (_busy ||
        _storageBroken ||
        _lost ||
        (!cancel && !lookup && !_form.currentState!.validate())) {
      return;
    }
    if (cancel &&
        !await _confirm(
          context,
          '이 요청을 취소할까요?',
          '아직 접수 여부를 모르는 요청도 전송 번호로 취소해요.',
          '요청 취소',
        )) {
      return;
    }
    if (!mounted || _lost) return;
    final generation = _generation;
    setState(() {
      _busy = true;
      _message = null;
      _recoverPending = false;
    });
    try {
      final pending = _pending ?? await widget.api.prepare(_kind, _text.text);
      if (!_current(generation)) return;
      setState(() => _pending = pending);
      final result = lookup
          ? await widget.api.lookup(pending)
          : cancel
          ? await widget.api.cancelPending(pending)
          : await widget.api.submit(pending);
      if (!_current(generation)) return;
      if (result == null) {
        setState(
          () => _message = '아직 접수 결과가 확인되지 않았어요. 같은 내용으로 보내거나 취소할 수 있어요.',
        );
      } else {
        setState(() {
          _pending = null;
          _text.clear();
          _message = result.withdrawn
              ? '요청을 취소했어요.'
              : '요청을 접수했어요. 아래에서 답변을 확인해 주세요.';
        });
        if (_scroll.hasClients) _scroll.jumpTo(0);
      }
      try {
        final history = await widget.api.history();
        if (_current(generation)) {
          setState(() {
            _history = history;
            _historyError = null;
          });
        }
      } catch (error) {
        if (_current(generation)) setState(() => _historyError = _error(error));
      }
    } catch (error) {
      if (_current(generation)) {
        setState(() {
          _message = _error(error);
          _recoverPending =
              error is ApiException && error.code == 'TOPIC_PENDING';
        });
      }
    } finally {
      if (_current(generation)) setState(() => _busy = false);
    }
  }

  Future<void> _leave() async {
    if (_busy || _loading) return;
    if (!await _confirm(
      context,
      '작성을 그만둘까요?',
      '아직 보내지 않은 글은 저장되지 않아요.',
      '나가기',
    )) {
      return;
    }
    if (!mounted) return;
    setState(() => _allowPop = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.of(context).pop();
    });
  }

  Future<void> _clearBroken() async {
    if (_busy ||
        _history == null ||
        _historyError != null ||
        !await _confirm(
          context,
          '이전 전송 정보를 정리할까요?',
          '아래 요청 내역을 먼저 확인해 주세요. 이미 보낸 요청은 삭제되지 않아요.',
          '확인 후 정리',
        )) {
      return;
    }
    if (!mounted || _lost || widget.api.owner != _owner) return;
    final generation = _generation;
    setState(() => _busy = true);
    try {
      await widget.api.clearBrokenPendingAfterReview();
      if (_current(generation)) {
        setState(() {
          _storageBroken = false;
          _message = null;
        });
      }
    } catch (error) {
      if (_current(generation)) setState(() => _message = _error(error));
    } finally {
      if (_current(generation)) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope<void>(
    canPop:
        _lost ||
        _allowPop ||
        (!_busy && (_pending != null || _text.text.trim().isEmpty)),
    onPopInvokedWithResult: (didPop, _) {
      if (!didPop) _leave();
    },
    child: Scaffold(
      appBar: AppBar(title: const Text('주제 요청 · 내역')),
      body: _lost
          ? const Center(child: Text('계정이 바뀌었어요. 화면을 닫고 다시 열어 주세요.'))
          : _loading
          ? const Center(child: CircularProgressIndicator())
          : Form(
              key: _form,
              child: ListView(
                controller: _scroll,
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 60),
                children: [
                  const Notice('필요한 생활 안내나 보고 싶은 영상 주제를 운영자에게 보낼 수 있어요.'),
                  if (_message != null) ...[
                    const SizedBox(height: 14),
                    Semantics(
                      liveRegion: true,
                      child: Notice(_message!, color: blue),
                    ),
                  ],
                  if (_recoverPending)
                    OutlinedButton(
                      onPressed: _busy
                          ? null
                          : () => Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) => TopicRequestsScreen(
                                  api: widget.api,
                                  settings: widget.settings,
                                ),
                              ),
                            ),
                      child: const Text('보내던 요청 확인'),
                    ),
                  if (_storageBroken) ...[
                    const SectionTitle('이전 요청을 확인해 주세요'),
                    OutlinedButton(
                      onPressed: _busy ? null : _load,
                      child: const Text('다시 확인'),
                    ),
                    OutlinedButton(
                      onPressed:
                          _busy || _history == null || _historyError != null
                          ? null
                          : _clearBroken,
                      child: const Text('요청 내역 확인 후 전송 정보 정리'),
                    ),
                  ] else ...[
                    const SectionTitle('어떤 주제를 원하세요?'),
                    Wrap(
                      spacing: 12,
                      runSpacing: 8,
                      children: [
                        for (final kind in TopicKind.values)
                          ChoiceChip(
                            label: Text(kind.label),
                            selected: _kind == kind,
                            onSelected: _busy || _pending != null
                                ? null
                                : (_) => setState(() => _kind = kind),
                          ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      key: const Key('topic-input'),
                      controller: _text,
                      readOnly: _pending != null,
                      enabled: !_busy,
                      maxLength: 60,
                      maxLines: 2,
                      decoration: const InputDecoration(
                        labelText: '원하는 주제',
                        hintText: '예: 휴대폰 글씨 크게 보기',
                      ),
                      onChanged: (_) => setState(() {}),
                      validator: (value) =>
                          value == null || value.trim().isEmpty
                          ? '주제를 적어 주세요.'
                          : value.contains(RegExp(r'[\x00-\x1f\x7f]'))
                          ? '주제를 한 줄로 적어 주세요.'
                          : null,
                    ),
                    if (_pending != null) ...[
                      const Notice('접수 결과를 확인하고 있어요. 이 내용은 기기에 안전하게 보관돼요.'),
                      const SizedBox(height: 12),
                      OutlinedButton(
                        onPressed: _busy ? null : () => _send(lookup: true),
                        child: const Text('접수 결과 확인'),
                      ),
                      const SizedBox(height: 8),
                      FilledButton(
                        onPressed: _busy ? null : _send,
                        child: Text(_busy ? '확인 중…' : '같은 내용으로 보내기'),
                      ),
                      TextButton(
                        onPressed: _busy ? null : () => _send(cancel: true),
                        child: const Text('보내던 요청 취소'),
                      ),
                    ] else
                      FilledButton(
                        key: const Key('send-topic'),
                        onPressed: _busy ? null : _send,
                        child: Text(_busy ? '보내는 중…' : '요청 보내기'),
                      ),
                  ],
                  const SectionTitle('내가 보낸 요청'),
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _historyPage(_history?.offset ?? 0),
                    icon: const Icon(Icons.refresh),
                    label: const Text('내역 새로고침'),
                  ),
                  if (_historyError != null)
                    Notice(_historyError!, color: blue),
                  if (_history != null && _history!.items.isEmpty)
                    const Padding(
                      padding: EdgeInsets.all(20),
                      child: Text('아직 보낸 요청이 없어요.'),
                    ),
                  for (final item in _history?.items ?? <TopicRecord>[])
                    Card(
                      child: ListTile(
                        contentPadding: const EdgeInsets.all(16),
                        title: Text(item.topic ?? '취소한 요청'),
                        subtitle: Text(
                          '${item.kind.label} · ${topicStatusLabels[item.status]}\n${_date(item.createdAt)}',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: _busy
                            ? null
                            : () async {
                                await Navigator.of(context).push(
                                  MaterialPageRoute<void>(
                                    builder: (_) => TopicDetailScreen(
                                      api: widget.api,
                                      settings: widget.settings,
                                      id: item.id,
                                    ),
                                  ),
                                );
                                if (mounted && !_lost) {
                                  _historyPage(_history?.offset ?? 0);
                                }
                              },
                      ),
                    ),
                  if (_history != null)
                    Wrap(
                      alignment: WrapAlignment.spaceBetween,
                      spacing: 12,
                      children: [
                        OutlinedButton(
                          onPressed: _busy || _history!.offset == 0
                              ? null
                              : () => _historyPage(
                                  (_history!.offset - 20).clamp(0, 10000),
                                ),
                          child: const Text('이전 내역'),
                        ),
                        OutlinedButton(
                          onPressed:
                              _busy ||
                                  _history!.offset + 20 >= _history!.total ||
                                  _history!.offset >= 10000
                              ? null
                              : () => _historyPage(_history!.offset + 20),
                          child: const Text('다음 내역'),
                        ),
                      ],
                    ),
                ],
              ),
            ),
    ),
  );
}

class TopicDetailScreen extends StatefulWidget {
  const TopicDetailScreen({
    required this.api,
    required this.settings,
    required this.id,
    super.key,
  });
  final TopicApi api;
  final AppSettings settings;
  final String id;
  @override
  State<TopicDetailScreen> createState() => _TopicDetailScreenState();
}

class _TopicDetailScreenState extends State<TopicDetailScreen> {
  late final String? _owner = widget.api.owner;
  late Future<TopicRecord> _future = widget.api.detail(widget.id);
  bool _busy = false;
  Future<void> _withdraw() async {
    if (_busy ||
        !await _confirm(context, '이 요청을 취소할까요?', '요청 내용과 답변이 지워져요.', '요청 취소')) {
      return;
    }
    if (!mounted || widget.api.owner != _owner) return;
    setState(() => _busy = true);
    try {
      await widget.api.withdraw(widget.id);
      if (mounted && widget.api.owner == _owner) {
        setState(() {
          _future = widget.api.detail(widget.id);
        });
      }
    } catch (error) {
      if (mounted && widget.api.owner == _owner) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(_error(error))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('요청과 답변')),
    body: ListenableBuilder(
      listenable: widget.api.identity,
      builder: (_, _) => widget.api.owner != _owner
          ? const Center(child: Text('다시 로그인해 주세요.'))
          : FutureBuilder(
              future: _future,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return _Retry(
                    message: _error(snapshot.error!),
                    retry: () => setState(() {
                      _future = widget.api.detail(widget.id);
                    }),
                  );
                }
                final item = snapshot.requireData;
                return ListView(
                  padding: const EdgeInsets.all(20),
                  children: [
                    Text(
                      item.topic ?? '취소한 요청',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      '${item.kind.label} · ${topicStatusLabels[item.status]}',
                    ),
                    Text('보낸 날 ${_date(item.createdAt)}'),
                    if (item.reply != null) ...[
                      const SectionTitle('운영자 답변'),
                      Text(item.reply!),
                    ],
                    if (item.guide != null) ...[
                      const SizedBox(height: 20),
                      FilledButton.icon(
                        onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => GuideReaderScreen(
                              api: widget.api,
                              settings: widget.settings,
                              summary: item.guide!,
                            ),
                          ),
                        ),
                        icon: const Icon(Icons.menu_book),
                        label: const Text('생활 안내 보기'),
                      ),
                    ] else if (item.kind == TopicKind.lifeGuide &&
                        item.status == 'completed')
                      const Notice('연결된 안내는 지금 볼 수 없어요. 나중에 다시 확인해 주세요.'),
                    if (!item.withdrawn) ...[
                      const SizedBox(height: 24),
                      OutlinedButton(
                        onPressed: _busy ? null : _withdraw,
                        child: Text(_busy ? '취소 확인 중…' : '요청 취소'),
                      ),
                    ],
                  ],
                );
              },
            ),
    ),
  );
}

class GuideCatalogScreen extends StatefulWidget {
  const GuideCatalogScreen({
    required this.api,
    required this.settings,
    super.key,
  });
  final TopicApi api;
  final AppSettings settings;
  @override
  State<GuideCatalogScreen> createState() => _GuideCatalogScreenState();
}

class _GuideCatalogScreenState extends State<GuideCatalogScreen> {
  int _offset = 0;
  late Future<TopicPage<GuideSummary>> _future = widget.api.guides();
  void _load(int offset) => setState(() {
    _offset = offset;
    _future = widget.api.guides(offset: offset);
  });
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('생활 안내')),
    body: Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => TopicRequestsScreen(
                    api: widget.api,
                    settings: widget.settings,
                  ),
                ),
              ),
              icon: const Icon(Icons.edit_note),
              label: const Text('필요한 안내 요청 · 내역'),
            ),
          ),
        ),
        Expanded(
          child: FutureBuilder(
            future: _future,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                return _Retry(
                  message: _error(snapshot.error!),
                  retry: () => _load(_offset),
                );
              }
              final page = snapshot.requireData;
              return ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  const Notice('검수 후 게시한 생활 안내를 볼 수 있어요.'),
                  if (page.items.isEmpty)
                    const Padding(
                      padding: EdgeInsets.all(24),
                      child: Text('아직 게시된 안내가 없어요. 필요한 주제를 요청해 주세요.'),
                    ),
                  for (final guide in page.items)
                    Card(
                      child: ListTile(
                        title: Text(guide.title),
                        subtitle: Text('자료 확인일 ${guide.checkedOn}'),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => GuideReaderScreen(
                              api: widget.api,
                              settings: widget.settings,
                              summary: guide,
                            ),
                          ),
                        ),
                      ),
                    ),
                  Wrap(
                    alignment: WrapAlignment.spaceBetween,
                    spacing: 12,
                    children: [
                      OutlinedButton(
                        onPressed: _offset == 0
                            ? null
                            : () => _load((_offset - 20).clamp(0, 10000)),
                        child: const Text('이전 안내'),
                      ),
                      OutlinedButton(
                        onPressed:
                            _offset + 20 >= page.total || _offset >= 10000
                            ? null
                            : () => _load(_offset + 20),
                        child: const Text('다음 안내'),
                      ),
                    ],
                  ),
                ],
              );
            },
          ),
        ),
      ],
    ),
  );
}

class GuideReaderScreen extends StatefulWidget {
  const GuideReaderScreen({
    required this.api,
    required this.settings,
    required this.summary,
    super.key,
  });
  final TopicApi api;
  final AppSettings settings;
  final GuideSummary summary;
  @override
  State<GuideReaderScreen> createState() => _GuideReaderScreenState();
}

class _GuideReaderScreenState extends State<GuideReaderScreen> {
  late Future<GuideContent> _future = widget.api.guide(widget.summary);
  @override
  void dispose() {
    widget.settings.stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('생활 안내 보기')),
    body: FutureBuilder(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return _Retry(
            message: _error(snapshot.error!),
            retry: () => setState(() {
              _future = widget.api.guide(widget.summary);
            }),
          );
        }
        final guide = snapshot.requireData;
        return ListView.builder(
          padding: const EdgeInsets.all(20),
          itemCount: guide.steps.length + 2,
          itemBuilder: (context, index) {
            if (index == 0) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    guide.summary.title,
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 12),
                  Text('자료 확인일 ${guide.summary.checkedOn}'),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: () async {
                      try {
                        await widget.settings.read(
                          guide.steps
                              .map((step) => '${step.title ?? ''} ${step.text}')
                              .join('\n'),
                        );
                      } catch (_) {
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text('음성 안내를 사용할 수 없어요. 설정을 확인해 주세요.'),
                            ),
                          );
                        }
                      }
                    },
                    icon: const Icon(Icons.volume_up_outlined),
                    label: const Text('안내 읽어주기'),
                  ),
                ],
              );
            }
            if (index == guide.steps.length + 1) {
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 20),
                child: Text('출처: ${guide.summary.source}'),
              );
            }
            final step = guide.steps[index - 1];
            return Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '$index단계${step.title == null ? '' : ' · ${step.title}'}',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      step.text,
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    ),
  );
}

class _Retry extends StatelessWidget {
  const _Retry({required this.message, required this.retry});
  final String message;
  final VoidCallback retry;
  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      Notice(message, color: blue),
      const SizedBox(height: 20),
      FilledButton(onPressed: retry, child: const Text('다시 시도')),
    ],
  );
}
