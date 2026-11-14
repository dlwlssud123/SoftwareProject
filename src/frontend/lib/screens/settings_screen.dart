import 'package:flutter/material.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/common.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({required this.settings, super.key});
  final AppSettings settings;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: settings,
    builder: (context, _) => Scaffold(
      backgroundColor: const Color(0xFFF3F3F7),
      appBar: AppBar(title: const Text('설정')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        children: [
          const SectionTitle('글자 크기'),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final entry in {
                      '보통': 1.0,
                      '크게': 1.2,
                      '아주 크게': 1.4,
                    }.entries)
                      ChoiceChip(
                        label: Text(entry.key),
                        selected: settings.textScale == entry.value,
                        onSelected: (_) => settings.setScale(entry.value),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 8,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 14),
                const Text(
                  '가나다 ABC 글자 크기 미리보기',
                  style: TextStyle(fontSize: 18, height: 1.5),
                ),
              ],
            ),
          ),
          const SectionTitle('음성 안내'),
          Material(
            color: Colors.white,
            borderRadius: BorderRadius.circular(10),
            child: SwitchListTile.adaptive(
              title: const Text('음성 안내 사용', style: TextStyle(fontSize: 18)),
              subtitle: const Text(
                '스피커 버튼을 누르면 읽어드려요',
                style: TextStyle(fontSize: 14),
              ),
              value: settings.voice,
              onChanged: settings.setVoice,
            ),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () =>
                readAloud(context, settings, '안녕하세요. 오늘동행이 편안한 하루를 함께할게요.'),
            icon: const Icon(Icons.volume_up_outlined),
            label: const Text('음성 미리 듣기'),
          ),
          TextButton(onPressed: settings.stop, child: const Text('읽어주기 중지')),
          const SectionTitle('개인정보 안내'),
          const Notice(
            '서버 연결 식단 추천에서는 식사·건강 조건을 전송하고 추천 결과를 서버에 보관해요. 전송 항목은 추천을 요청하기 전에 안내해요. 사진은 기기에서만 사용해요.',
            color: muted,
          ),
          const SectionTitle('앱 정보'),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '오늘동행 · ValueFlow',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                ),
                SizedBox(height: 6),
                Text(
                  '발표용 프로토타입 0.1.0',
                  style: TextStyle(fontSize: 14, color: muted),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          const Text(
            '식단과 복지는 공식 API에서 수집한 정보를 사용해요. 영상 버튼은 YouTube 검색으로 연결돼요.',
            style: TextStyle(fontSize: 14, color: muted, height: 1.5),
          ),
        ],
      ),
    ),
  );
}
