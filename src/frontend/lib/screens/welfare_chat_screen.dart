import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import '../core/network/api_exception.dart';
import '../data/ai_api.dart';
import '../models/welfare_chat.dart';
import '../services/settings.dart';
import '../widgets/ai_consent.dart';
import '../widgets/common.dart';

class WelfareChatScreen extends StatefulWidget {
  const WelfareChatScreen({
    required this.api,
    required this.settings,
    super.key,
  });
  final AiApi api;
  final AppSettings settings;
  @override
  State<WelfareChatScreen> createState() => _WelfareChatScreenState();
}

class _WelfareChatScreenState extends State<WelfareChatScreen> {
  final _question = TextEditingController();
  final _district = TextEditingController();
  String _region = '';
  bool _busy = false, _consented = false;
  String? _error;
  WelfareChatAnswer? _answer;
  CancelToken? _request;
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

  Future<void> _send() async {
    final question = _question.text.trim();
    if (question.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _answer = null;
    });
    try {
      if (!_consented) {
        final allowed = await confirmAiProcessing(context, photo: false);
        if (!allowed || !mounted) return;
        setState(() => _consented = true);
      }
      _request = CancelToken();
      final answer = await widget.api.welfareChat(
        question,
        _request!,
        region: _region.isEmpty ? null : _region,
        district: _region.isEmpty || _district.text.trim().isEmpty
            ? null
            : _district.text.trim(),
      );
      if (mounted) setState(() => _answer = answer);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _request?.cancel();
    _question.dispose();
    _district.dispose();
    widget.settings.stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('복지 물어보기')),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Notice(
          '공식 복지 자료를 찾아 안내해요. 지역을 선택하지 않으면 전국 사업만 찾아요. 이름·소득·건강기록은 적지 마세요.',
        ),
        ExpansionTile(
          title: const Text('지역 설정 (선택)'),
          children: [
            DropdownButtonFormField<String>(
              key: const Key('rag-region'),
              initialValue: _region,
              isExpanded: true,
              decoration: const InputDecoration(labelText: '시·도'),
              items: [
                const DropdownMenuItem(value: '', child: Text('전국 사업만')),
                for (final region in regions)
                  DropdownMenuItem(
                    value: region,
                    child: Text(region, overflow: TextOverflow.ellipsis),
                  ),
              ],
              onChanged: _busy
                  ? null
                  : (value) => setState(() {
                      _region = value!;
                      _district.clear();
                      _answer = null;
                    }),
            ),
            TextField(
              key: const Key('rag-district'),
              controller: _district,
              maxLength: 50,
              enabled: !_busy && _region.isNotEmpty,
              decoration: const InputDecoration(
                labelText: '시·군·구 (선택)',
                hintText: '예: 남구',
              ),
              onChanged: (_) => setState(() => _answer = null),
            ),
          ],
        ),
        const SizedBox(height: 12),
        TextField(
          key: const Key('rag-question'),
          controller: _question,
          enabled: !_busy,
          minLines: 2,
          maxLines: 5,
          maxLength: 500,
          decoration: const InputDecoration(
            labelText: '궁금한 복지를 물어보세요',
            hintText: '예: 혼자 사는데 안부를 확인해 주는 지원이 있나요?',
          ),
        ),
        for (final sample in [
          '혼자 사는데 안부를 확인해 주는 지원이 있나요?',
          '겨울 난방비를 도와주는 지원이 있나요?',
        ])
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: OutlinedButton(
              onPressed: _busy
                  ? null
                  : () => setState(() {
                      _question.text = sample;
                      _answer = null;
                    }),
              child: Text(sample),
            ),
          ),
        FilledButton.icon(
          key: const Key('rag-send'),
          onPressed: _busy ? null : _send,
          icon: const Icon(Icons.search),
          label: Text(_busy ? '공식 자료를 찾고 있어요…' : '복지 자료 찾아보기'),
        ),
        if (_busy && _consented) const LinearProgressIndicator(),
        if (_error != null) Notice(_error!),
        if (_answer case final answer?) ...[
          const SectionTitle('찾은 안내'),
          if (answer.evidence == 'weak')
            const Notice('질문과 꼭 맞는 자료가 아닐 수 있어요. 원문의 지원 대상과 조건을 함께 확인해 주세요.'),
          for (final note in answer.notes) Notice(note),
          Text(
            [
                  answer.region,
                  answer.district,
                ].whereType<String>().join(' ').isEmpty
                ? '전국 사업 검색 결과'
                : '${[answer.region, answer.district].whereType<String>().join(' ')} · 전국 사업 검색 결과',
          ),
          const SizedBox(height: 10),
          SelectableText(
            answer.answer,
            style: const TextStyle(fontSize: 18, height: 1.6),
          ),
          OutlinedButton.icon(
            onPressed: () => readAloud(context, widget.settings, answer.answer),
            icon: const Icon(Icons.volume_up_outlined),
            label: const Text('답변 읽어주기'),
          ),
          Notice(answer.notice),
          if (answer.sources.isNotEmpty) const SectionTitle('확인한 공식 자료'),
          for (final source in answer.sources)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      '[${source.number}] ${source.title}',
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    if (source.checkedAt != null)
                      Text(
                        '자료 확인: ${source.checkedAt!.toIso8601String().substring(0, 10)}',
                      ),
                    const SizedBox(height: 8),
                    Text(source.excerpt),
                    if (source.url != null)
                      OutlinedButton.icon(
                        onPressed: () => openLink(context, source.url!),
                        icon: const Icon(Icons.open_in_new),
                        label: const Text('공식 안내 열기'),
                      ),
                  ],
                ),
              ),
            ),
        ],
        const SizedBox(height: 24),
      ],
    ),
  );
}
