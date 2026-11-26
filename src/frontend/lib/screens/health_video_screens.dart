import '../services/usage_recorder.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../core/network/api_exception.dart';
import '../data/health_video_api.dart';
import '../models/health_video.dart';
import '../services/settings.dart';
import '../widgets/common.dart';

String _error(Object error) =>
    error is ApiException ? error.message : '영상 정보를 확인하지 못했어요. 다시 시도해 주세요.';

class HealthVideoCatalog extends StatefulWidget {
  const HealthVideoCatalog({
    required this.api,
    required this.settings,
    super.key,
  });
  final HealthVideoApi api;
  final AppSettings settings;
  @override
  State<HealthVideoCatalog> createState() => _HealthVideoCatalogState();
}

class _HealthVideoCatalogState extends State<HealthVideoCatalog> {
  HealthVideoPage? page;
  VideoTopic? topic;
  String? error;
  bool loading = true;
  int offset = 0;
  CancelToken? request;
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    request?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    request?.cancel();
    final current = request = CancelToken();
    setState(() {
      loading = true;
      error = null;
      page = null;
    });
    try {
      final result = await widget.api.list(
        topic: topic,
        offset: offset,
        cancelToken: current,
      );
      if (mounted && !current.isCancelled) setState(() => page = result);
    } on Object catch (e) {
      if (mounted && !current.isCancelled) setState(() => error = _error(e));
    } finally {
      if (mounted && !current.isCancelled) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const Text('출처를 확인한 기관 영상을 골라 보세요. 누르면 YouTube에서 재생해요.'),
      const SizedBox(height: 12),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final value in [null, ...VideoTopic.values])
            ChoiceChip(
              label: Text(value?.label ?? '전체'),
              selected: topic == value,
              onSelected: (_) {
                setState(() {
                  topic = value;
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
        OutlinedButton(onPressed: _load, child: const Text('건강 영상 다시 불러오기')),
      ] else if (page case final result?) ...[
        if (result.items.isEmpty)
          const Text('이 주제에 등록된 영상이 아직 없어요. 다른 주제를 골라 주세요.'),
        for (final video in result.items)
          FeatureTile(
            key: Key('health-video-${video.id}'),
            title: video.title,
            subtitle:
                '${video.topic.label} · ${video.publisher}\n출처 확인 ${video.checkedOn}',
            icon: Icons.play_circle_outline,
            onTap: () => Navigator.push<void>(
              context,
              MaterialPageRoute(
                builder: (_) => HealthVideoDetail(
                  api: widget.api,
                  id: video.id,
                  settings: widget.settings,
                ),
              ),
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
                child: const Text('이전 영상'),
              ),
            if (result.hasNext)
              OutlinedButton(
                onPressed: () {
                  offset += result.limit;
                  _load();
                },
                child: const Text('다음 영상'),
              ),
          ],
        ),
      ],
    ],
  );
}

class HealthVideoDetail extends StatefulWidget {
  const HealthVideoDetail({
    required this.api,
    required this.id,
    required this.settings,
    super.key,
  });
  final HealthVideoApi api;
  final String id;
  final AppSettings settings;
  @override
  State<HealthVideoDetail> createState() => _HealthVideoDetailState();
}

class _HealthVideoDetailState extends State<HealthVideoDetail> {
  HealthVideo? video;
  String? error;
  bool loading = true;
  CancelToken? request;
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    request?.cancel();
    widget.settings.stop();
    super.dispose();
  }

  Future<void> _load() async {
    request?.cancel();
    final current = request = CancelToken();
    setState(() {
      loading = true;
      error = null;
      video = null;
    });
    try {
      final result = await widget.api.detail(widget.id, cancelToken: current);
      if (mounted && !current.isCancelled) setState(() => video = result);
    } on Object catch (e) {
      if (mounted && !current.isCancelled) setState(() => error = _error(e));
    } finally {
      if (mounted && !current.isCancelled) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('건강 영상 보기')),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        if (loading) const Center(child: CircularProgressIndicator()),
        if (error != null) ...[
          Text(error!),
          OutlinedButton(onPressed: _load, child: const Text('영상 다시 확인하기')),
        ],
        if (video case final item?) ...[
          Text(item.title, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 16),
          Text('게시 기관: ${item.publisher}'),
          Text('주제: ${item.topic.label}'),
          Text('출처 확인: ${item.checkedOn}'),
          const SizedBox(height: 20),
          FilledButton.icon(
            key: const Key('health-video-play'),
            onPressed: () {
              UsageRecorder.current?.record(
                'video_open',
                'shorts',
                action: 'open',
              );
              openLink(context, item.watchUrl);
            },
            icon: const Icon(Icons.play_arrow),
            label: const Text('YouTube에서 영상 재생'),
          ),
          OutlinedButton.icon(
            onPressed: () => readAloud(
              context,
              widget.settings,
              '${item.title}. ${item.publisher}의 영상이에요. 영상 재생 버튼을 누르면 YouTube로 이동해요.',
            ),
            icon: const Icon(Icons.volume_up_outlined),
            label: const Text('영상 안내 읽어주기'),
          ),
          OutlinedButton.icon(
            onPressed: () => openLink(context, item.sourceUrl),
            icon: const Icon(Icons.open_in_new),
            label: const Text('기관 출처 보기'),
          ),
          const SizedBox(height: 16),
          const Text('영상이 재생되지 않으면 삭제되었거나 이용이 제한됐을 수 있어요. 목록에서 다른 영상을 골라 주세요.'),
          const SizedBox(height: 12),
          const Notice(
            '자동 재생하지 않아요. YouTube 앱이나 브라우저로 이동하며 데이터가 사용될 수 있어요. 영상 길이는 각각 달라요.',
          ),
        ],
      ],
    ),
  );
}
