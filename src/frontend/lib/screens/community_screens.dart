import 'package:flutter/material.dart';
import '../core/network/api_exception.dart';
import '../data/community_api.dart';
import '../models/community.dart';
import '../services/settings.dart';
import '../widgets/common.dart';

String _message(Object error) =>
    error is ApiException ? error.message : '처리하지 못했어요. 연결을 확인하고 다시 시도해 주세요.';
String _date(DateTime date) {
  final local = date.toUtc().add(const Duration(hours: 9));
  return '${local.year}.${local.month}.${local.day}';
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
        content: SingleChildScrollView(child: Text(text)),
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

/// A route must never display the previous account's posts or draft after a switch.
class _Identity extends StatefulWidget {
  const _Identity({required this.api, required this.child});
  final CommunityApi api;
  final Widget child;
  @override
  State<_Identity> createState() => _IdentityState();
}

class _IdentityState extends State<_Identity> {
  late final _owner = widget.api.owner;
  bool lost = false;
  @override
  void initState() {
    super.initState();
    widget.api.identity.addListener(_changed);
  }

  void _changed() {
    if (widget.api.owner != _owner && !lost && mounted) {
      setState(() => lost = true);
    }
  }

  @override
  void dispose() {
    widget.api.identity.removeListener(_changed);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => lost || _owner == null
      ? Scaffold(
          appBar: AppBar(title: const Text('이웃 이야기')),
          body: const Padding(
            padding: EdgeInsets.all(24),
            child: Text('계정을 확인한 뒤 커뮤니티를 다시 열어 주세요.'),
          ),
        )
      : widget.child;
}

class CommunityScreen extends StatelessWidget {
  const CommunityScreen({required this.api, required this.settings, super.key});
  final CommunityApi api;
  final AppSettings settings;
  @override
  Widget build(BuildContext context) => _Identity(
    api: api,
    child: _Feed(api: api, settings: settings),
  );
}

class _Feed extends StatefulWidget {
  const _Feed({required this.api, required this.settings});
  final CommunityApi api;
  final AppSettings settings;
  @override
  State<_Feed> createState() => _FeedState();
}

class _FeedState extends State<_Feed> {
  CommunityPage<CommunityPost>? page;
  CommunityCategory? category;
  bool mine = false, loading = true;
  String? error;
  int offset = 0, generation = 0;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final current = ++generation;
    setState(() {
      loading = true;
      error = null;
      page = null;
    });
    try {
      final result = await widget.api.posts(
        mine: mine,
        category: category,
        offset: offset,
      );
      if (mounted && current == generation) setState(() => page = result);
    } on Object catch (e) {
      if (mounted && current == generation) setState(() => error = _message(e));
    } finally {
      if (mounted && current == generation) setState(() => loading = false);
    }
  }

  Future<void> _open(CommunityPost post) async {
    await Navigator.push<void>(
      context,
      MaterialPageRoute(
        builder: (_) => _Identity(
          api: widget.api,
          child: _PostDetail(
            api: widget.api,
            id: post.id,
            settings: widget.settings,
          ),
        ),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _write() async {
    final post = await Navigator.push<CommunityPost>(
      context,
      MaterialPageRoute(
        builder: (_) => _Identity(
          api: widget.api,
          child: _Compose(api: widget.api),
        ),
      ),
    );
    if (!mounted) return;
    if (post != null) {
      await _open(post);
    } else {
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('이웃 이야기')),
    body: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Notice('식사와 일상을 나눠 보세요. 이름·주소·전화번호·건강정보는 적지 마세요.'),
        const SizedBox(height: 12),
        FilledButton.icon(
          key: const Key('community-write'),
          onPressed: _write,
          icon: const Icon(Icons.edit_outlined),
          label: const Text('이야기 쓰기'),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final own in [false, true])
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () {
                        setState(() {
                          mine = own;
                          offset = 0;
                        });
                        _load();
                      },
                child: Text(
                  own == mine
                      ? '✓ ${own ? '내 글' : '이웃 글'}'
                      : own
                      ? '내 글'
                      : '이웃 글',
                ),
              ),
            OutlinedButton(
              onPressed: () async {
                await Navigator.push<void>(
                  context,
                  MaterialPageRoute(
                    builder: (_) => _Identity(
                      api: widget.api,
                      child: _Blocks(api: widget.api),
                    ),
                  ),
                );
                if (mounted) _load();
              },
              child: const Text('차단 관리'),
            ),
          ],
        ),
        if (!mine)
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final value in [null, ...CommunityCategory.values])
                ChoiceChip(
                  label: Text(value?.label ?? '전체'),
                  selected: category == value,
                  onSelected: loading
                      ? null
                      : (_) {
                          setState(() {
                            category = value;
                            offset = 0;
                          });
                          _load();
                        },
                ),
            ],
          ),
        const SizedBox(height: 12),
        if (loading)
          const Center(child: CircularProgressIndicator())
        else if (error != null) ...[
          Text(error!),
          OutlinedButton(onPressed: _load, child: const Text('다시 불러오기')),
        ] else if (page case final result?) ...[
          Text(mine ? '내가 쓴 글 ${result.total}개' : '이웃 글 ${result.total}개'),
          if (result.items.isEmpty)
            const Padding(
              padding: EdgeInsets.all(20),
              child: Text('아직 이야기가 없어요. 첫 이야기를 나눠 보세요.'),
            ),
          for (final post in result.items)
            Card(
              child: ListTile(
                key: Key('community-post-${post.id}'),
                contentPadding: const EdgeInsets.all(16),
                title: Text(post.title),
                subtitle: Text(
                  '${post.category.label} · ${post.authorLabel}\n${_date(post.createdAt)}${post.status == 'hidden' ? '\n관리자가 숨긴 글이에요' : ''}',
                ),
                isThreeLine: true,
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(post),
              ),
            ),
          Wrap(
            spacing: 12,
            children: [
              if (offset > 0)
                OutlinedButton(
                  onPressed: () {
                    offset = (offset - 20).clamp(0, offset);
                    _load();
                  },
                  child: const Text('이전 글'),
                ),
              if (result.hasNext)
                OutlinedButton(
                  onPressed: () {
                    offset += result.limit;
                    _load();
                  },
                  child: const Text('다음 글'),
                ),
              TextButton(
                onPressed: () {
                  offset = 0;
                  _load();
                },
                child: const Text('새로고침'),
              ),
            ],
          ),
        ],
      ],
    ),
  );
}

class _PostDetail extends StatefulWidget {
  const _PostDetail({
    required this.api,
    required this.id,
    required this.settings,
  });
  final CommunityApi api;
  final String id;
  final AppSettings settings;
  @override
  State<_PostDetail> createState() => _PostDetailState();
}

class _PostDetailState extends State<_PostDetail> {
  CommunityPost? post;
  bool loading = true, busy = false;
  String? error;
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    widget.settings.stop();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
      post = null;
    });
    try {
      final row = await widget.api.detail(widget.id);
      if (mounted) setState(() => post = row);
    } on Object catch (e) {
      if (mounted) setState(() => error = _message(e));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _act(
    Future<void> Function() action,
    String done, {
    bool leave = false,
  }) async {
    if (busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
      if (leave) Navigator.pop(context);
    } on Object catch (e) {
      if (mounted) setState(() => error = _message(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _report() async {
    const labels = {
      'spam': '광고·도배',
      'abuse': '욕설·괴롭힘',
      'misinformation': '잘못된 정보',
      'privacy': '개인정보 노출',
      'other': '그 밖의 문제',
    };
    final reason = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('어떤 문제가 있나요?'),
        children: [
          for (final entry in labels.entries)
            SimpleDialogOption(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 18),
              onPressed: () => Navigator.pop(context, entry.key),
              child: Text(entry.value),
            ),
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
        ],
      ),
    );
    if (reason != null && mounted) {
      await _act(
        () => widget.api.report(widget.id, reason),
        '신고를 접수했어요. 관리자가 확인할게요.',
      );
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: Scaffold(
      appBar: AppBar(title: const Text('이야기 보기')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (loading) const Center(child: CircularProgressIndicator()),
          if (error != null) ...[
            Text(error!),
            OutlinedButton(
              onPressed: busy ? null : _load,
              child: const Text('글 다시 확인하기'),
            ),
          ],
          if (post case final row?) ...[
            Text(row.category.label),
            Text(row.title, style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 12),
            Text('${row.authorLabel} · ${_date(row.createdAt)}'),
            if (row.status == 'hidden') const Notice('다른 이용자에게는 보이지 않는 글이에요.'),
            const SizedBox(height: 20),
            SelectableText(row.body),
            const SizedBox(height: 20),
            OutlinedButton.icon(
              onPressed: busy
                  ? null
                  : () => readAloud(
                      context,
                      widget.settings,
                      '${row.title}. ${row.body}',
                    ),
              icon: const Icon(Icons.volume_up_outlined),
              label: const Text('읽어주기'),
            ),
            if (row.isMine)
              OutlinedButton.icon(
                onPressed: busy
                    ? null
                    : () async {
                        if (await _confirm(
                              context,
                              '글을 삭제할까요?',
                              '삭제하면 다른 사람이 볼 수 없고 되돌릴 수 없어요.',
                              '삭제하기',
                            ) &&
                            mounted) {
                          await _act(
                            () => widget.api.remove(row),
                            '글을 삭제했어요.',
                            leave: true,
                          );
                        }
                      },
                icon: const Icon(Icons.delete_outline),
                label: const Text('내 글 삭제'),
              )
            else ...[
              OutlinedButton.icon(
                onPressed: busy ? null : _report,
                icon: const Icon(Icons.flag_outlined),
                label: const Text('문제 있는 글 신고'),
              ),
              OutlinedButton.icon(
                onPressed: busy
                    ? null
                    : () async {
                        if (await _confirm(
                              context,
                              '이 작성자를 차단할까요?',
                              '서로의 글이 보이지 않아요. 차단 관리에서 해제할 수 있어요.',
                              '차단하기',
                            ) &&
                            mounted) {
                          await _act(
                            () => widget.api.block(row.id),
                            '작성자를 차단했어요.',
                            leave: true,
                          );
                        }
                      },
                icon: const Icon(Icons.block),
                label: const Text('이 작성자 차단'),
              ),
            ],
            if (busy) const Text('처리하고 있어요. 잠시 기다려 주세요.'),
          ],
        ],
      ),
    ),
  );
}

class _Compose extends StatefulWidget {
  const _Compose({required this.api});
  final CommunityApi api;
  @override
  State<_Compose> createState() => _ComposeState();
}

class _ComposeState extends State<_Compose> {
  final form = GlobalKey<FormState>();
  final title = TextEditingController(), body = TextEditingController();
  CommunityCategory category = CommunityCategory.meal;
  PendingCommunityPost? pending;
  bool loading = true, busy = false, allowPop = false, acknowledged = false;
  String? error;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final previous = await widget.api.pending();
      if (!mounted) return;
      setState(() {
        pending = previous;
        if (previous != null) {
          title.text = previous.title;
          body.text = previous.body;
          category = previous.category;
          acknowledged = true;
        }
      });
    } on Object catch (e) {
      if (mounted) setState(() => error = _message(e));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  void dispose() {
    title.dispose();
    body.dispose();
    super.dispose();
  }

  Future<void> _leave() async {
    if (busy || allowPop) return;
    if (title.text.isNotEmpty || body.text.isNotEmpty) {
      if (!await _confirm(
        context,
        '글쓰기에서 나갈까요?',
        pending == null
            ? '아직 보내지 않은 내용은 저장되지 않아요.'
            : '이전 전송 정보를 보관할게요. 다시 글쓰기를 열어 같은 요청의 결과를 확인해 주세요.',
        '나가기',
      )) {
        return;
      }
    }
    if (!mounted) return;
    setState(() => allowPop = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.pop(context);
    });
  }

  Future<void> _send() async {
    if (busy || !acknowledged || !form.currentState!.validate()) return;
    if (pending == null &&
        !await _confirm(
          context,
          '이야기를 공개할까요?',
          '다른 이용자들이 이 글을 볼 수 있어요. 개인정보가 없는지 확인해 주세요.',
          '공개하기',
        )) {
      return;
    }
    if (!mounted) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final receipt =
          pending ?? await widget.api.prepare(category, title.text, body.text);
      if (!mounted) return;
      setState(() {
        pending = receipt;
        title.text = receipt.title;
        body.text = receipt.body;
        category = receipt.category;
      });
      final result = await widget.api.submit(receipt);
      if (!mounted) return;
      setState(() {
        allowPop = true;
        busy = false;
      });
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) Navigator.pop(context, result);
      });
    } on Object catch (e) {
      if (mounted) setState(() => error = _message(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String? _validate(String? value, int max) =>
      value == null || value.trim().isEmpty
      ? '내용을 입력해 주세요.'
      : value.trim().runes.length > max
      ? '$max자 안에 적어 주세요.'
      : null;
  @override
  Widget build(BuildContext context) => PopScope(
    canPop: allowPop,
    onPopInvokedWithResult: (didPop, _) {
      if (!didPop) _leave();
    },
    child: Scaffold(
      appBar: AppBar(title: const Text('이야기 쓰기')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : Form(
              key: form,
              child: ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  const Notice('이름·주소·전화번호·건강정보는 적지 마세요. 글은 다른 이용자에게 공개돼요.'),
                  if (pending != null)
                    const Notice(
                      '이전 전송 결과를 확인할게요. 같은 요청으로 다시 보내도 글이 중복되지 않아요.',
                    ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final value in CommunityCategory.values)
                        ChoiceChip(
                          label: Text(value.label),
                          selected: category == value,
                          onSelected: busy || pending != null
                              ? null
                              : (_) => setState(() => category = value),
                        ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const Key('community-title'),
                    controller: title,
                    readOnly: busy || pending != null,
                    maxLength: 60,
                    decoration: const InputDecoration(labelText: '제목'),
                    validator: (value) => _validate(value, 60),
                  ),
                  TextFormField(
                    key: const Key('community-body'),
                    controller: body,
                    readOnly: busy || pending != null,
                    maxLength: 2000,
                    minLines: 5,
                    maxLines: 12,
                    decoration: const InputDecoration(labelText: '나누고 싶은 이야기'),
                    validator: (value) => _validate(value, 2000),
                  ),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: acknowledged,
                    onChanged: busy || pending != null
                        ? null
                        : (value) =>
                              setState(() => acknowledged = value ?? false),
                    title: const Text('다른 사람이 보는 글이며, 개인정보를 적지 않았어요.'),
                  ),
                  if (error != null) Text(error!),
                  FilledButton(
                    key: const Key('community-send'),
                    onPressed: busy || !acknowledged ? null : _send,
                    child: Text(
                      busy
                          ? '확인하고 있어요…'
                          : pending != null
                          ? '같은 요청 결과 확인'
                          : '이야기 공개하기',
                    ),
                  ),
                ],
              ),
            ),
    ),
  );
}

class _Blocks extends StatefulWidget {
  const _Blocks({required this.api});
  final CommunityApi api;
  @override
  State<_Blocks> createState() => _BlocksState();
}

class _BlocksState extends State<_Blocks> {
  CommunityPage<CommunityBlock>? page;
  String? error;
  bool busy = false;
  int offset = 0;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      page = null;
      error = null;
      busy = true;
    });
    try {
      final result = await widget.api.blocks(offset: offset);
      if (mounted) setState(() => page = result);
    } on Object catch (e) {
      if (mounted) setState(() => error = _message(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: Scaffold(
      appBar: AppBar(title: const Text('차단 관리')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text('차단을 해제하면 서로의 글을 다시 볼 수 있어요.'),
          if (busy) const Center(child: CircularProgressIndicator()),
          if (error != null) ...[
            Text(error!),
            OutlinedButton(
              onPressed: busy ? null : _load,
              child: const Text('다시 불러오기'),
            ),
          ],
          if (page case final result?) ...[
            if (result.items.isEmpty) const Text('차단한 사람이 없어요.'),
            for (final row in result.items)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(row.authorLabel),
                      OutlinedButton(
                        onPressed: busy
                            ? null
                            : () async {
                                if (!await _confirm(
                                      context,
                                      '차단을 해제할까요?',
                                      '서로의 글을 다시 볼 수 있어요.',
                                      '해제하기',
                                    ) ||
                                    !mounted) {
                                  return;
                                }
                                setState(() {
                                  busy = true;
                                  error = null;
                                });
                                try {
                                  await widget.api.unblock(row.id);
                                  if (mounted) await _load();
                                } on Object catch (e) {
                                  if (mounted) {
                                    setState(() => error = _message(e));
                                  }
                                } finally {
                                  if (mounted) setState(() => busy = false);
                                }
                              },
                        child: const Text('차단 해제'),
                      ),
                    ],
                  ),
                ),
              ),
            Wrap(
              spacing: 12,
              children: [
                if (offset > 0)
                  OutlinedButton(
                    onPressed: busy
                        ? null
                        : () {
                            offset = (offset - 20).clamp(0, offset);
                            _load();
                          },
                    child: const Text('이전 목록'),
                  ),
                if (result.hasNext)
                  OutlinedButton(
                    onPressed: busy
                        ? null
                        : () {
                            offset += result.limit;
                            _load();
                          },
                    child: const Text('다음 목록'),
                  ),
              ],
            ),
          ],
        ],
      ),
    ),
  );
}
