import 'dart:async';
import 'package:flutter/material.dart';
import '../theme.dart';
import '../widgets/common.dart';

class ContentScreen extends StatefulWidget {
  const ContentScreen({this.playground = false, super.key});
  final bool playground;
  @override
  State<ContentScreen> createState() => _ContentScreenState();
}

class _ContentScreenState extends State<ContentScreen> {
  final requested = <String>[];
  static const health = [
    (
      title: '의자 스트레칭',
      category: '건강·운동',
      query: '시니어 의자 스트레칭',
      icon: Icons.accessibility_new_rounded,
      color: Color(0xFFE4EEDC),
    ),
    (
      title: '부드러운 한 끼',
      category: '요리·식사',
      query: '부드러운 어르신 요리',
      icon: Icons.soup_kitchen_outlined,
      color: Color(0xFFFAEACF),
    ),
    (
      title: '편안한 호흡',
      category: '건강·운동',
      query: '시니어 편안한 호흡 운동',
      icon: Icons.air_rounded,
      color: Color(0xFFE5EDF5),
    ),
    (
      title: '웃음 체조',
      category: '재미·웃음',
      query: '시니어 웃음 체조',
      icon: Icons.sentiment_very_satisfied_rounded,
      color: Color(0xFFF7E4DA),
    ),
  ];
  static const play = [
    (
      title: '같은 그림을 찾아보세요',
      category: '두뇌체조',
      query: '',
      icon: Icons.grid_view_rounded,
      color: Color(0xFFE4EEDC),
    ),
    (
      title: '추억의 풍경을 만나요',
      category: '그때 그 시절',
      query: '한국 옛날 풍경 추억',
      icon: Icons.photo_album_outlined,
      color: Color(0xFFFAEACF),
    ),
    (
      title: '집에서 시작하는 작은 취미',
      category: '소소한 취미',
      query: '시니어 쉬운 취미 종이접기',
      icon: Icons.palette_outlined,
      color: Color(0xFFE5EDF5),
    ),
    (
      title: '좋아하는 노래를 불러요',
      category: '노래교실',
      query: '시니어 노래교실',
      icon: Icons.music_note_outlined,
      color: Color(0xFFF7E4DA),
    ),
    (
      title: '천천히 배우는 바둑',
      category: '바둑·장기',
      query: '바둑 기초 배우기',
      icon: Icons.sports_esports_outlined,
      color: Color(0xFFE4EEDC),
    ),
    (
      title: '화면으로 떠나는 여행',
      category: '여행·명소',
      query: '한국 아름다운 여행지 영상',
      icon: Icons.landscape_outlined,
      color: Color(0xFFE5EDF5),
    ),
    (
      title: '귀여운 동물과 쉬어가요',
      category: '반려동물',
      query: '귀여운 반려동물 영상',
      icon: Icons.pets_outlined,
      color: Color(0xFFFAEACF),
    ),
  ];

  Future<void> requestTheme() async {
    final controller = TextEditingController();
    final value = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('어떤 주제를 보고 싶으세요?'),
        content: TextField(
          controller: controller,
          maxLength: 60,
          decoration: const InputDecoration(hintText: '예: 베란다에서 꽃 키우기'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('취소'),
          ),
          TextButton(
            onPressed: () {
              if (controller.text.trim().isNotEmpty) {
                Navigator.of(ctx).pop(controller.text.trim());
              }
            },
            child: const Text('메모하기'),
          ),
        ],
      ),
    );
    // Wait until the closing dialog releases its text field.
    await Future<void>.delayed(const Duration(milliseconds: 250));
    controller.dispose();
    if (value != null && mounted) setState(() => requested.add(value));
  }

  @override
  Widget build(BuildContext context) {
    final items = widget.playground ? play : health;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 24),
      children: [
        if (widget.playground) ...[
          const Notice(
            '보고 싶은 주제를 골라보세요.\n두뇌체조는 앱에서 바로 시작할 수 있어요.',
            icon: Icons.sports_esports_outlined,
            color: blue,
          ),
          const SizedBox(height: 18),
          ServiceGrid(
            children: [
              for (final item in items)
                ServiceButton(
                  title: item.category,
                  subtitle: item.title,
                  icon: item.icon,
                  background: item.color,
                  onTap: () {
                    if (item.query.isEmpty) {
                      Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) => const MemoryGame(),
                        ),
                      );
                    } else {
                      openLink(
                        context,
                        Uri.https('www.youtube.com', '/results', {
                          'search_query': item.query,
                        }),
                      );
                    }
                  },
                ),
            ],
          ),
        ] else ...[
          const Notice(
            '건강쇼츠 이용 안내\n• 보고 싶은 영상 주제를 눌러 주세요.\n• YouTube 검색 화면에서 영상을 볼 수 있어요.',
            color: blue,
          ),
          const SizedBox(height: 14),
          FeatureTile(
            title: '바로 보기',
            subtitle: '가벼운 운동 영상부터 찾아보세요',
            icon: Icons.play_circle_fill_rounded,
            color: const Color(0xFFE34135),
            onTap: () => openLink(
              context,
              Uri.https('www.youtube.com', '/results', {
                'search_query': health.first.query,
              }),
            ),
          ),
          for (final category
              in items.map((item) => item.category).toSet()) ...[
            SectionTitle(category),
            ServiceGrid(
              children: [
                for (final item in items.where(
                  (item) => item.category == category,
                ))
                  ServiceButton(
                    title: item.title,
                    icon: item.icon,
                    background: item.color,
                    onTap: () => openLink(
                      context,
                      Uri.https('www.youtube.com', '/results', {
                        'search_query': item.query,
                      }),
                    ),
                  ),
              ],
            ),
          ],
        ],
        const SizedBox(height: 22),
        OutlinedButton.icon(
          onPressed: requestTheme,
          icon: const Icon(Icons.edit_note_rounded),
          label: const Text('보고 싶은 주제 메모하기'),
        ),
        if (requested.isNotEmpty) ...[
          const SectionTitle('메모한 주제'),
          for (final request in requested)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.bookmark_border_rounded, color: blue),
              title: Text(request),
              subtitle: const Text(
                '현재 화면에서만 보관해요',
                style: TextStyle(fontSize: 14),
              ),
            ),
        ],
        const SizedBox(height: 12),
        const Text(
          '영상은 외부 YouTube 검색으로 연결돼요.',
          style: TextStyle(fontSize: 14, color: muted),
        ),
      ],
    );
  }
}

class MemoryGame extends StatefulWidget {
  const MemoryGame({super.key});
  @override
  State<MemoryGame> createState() => _MemoryGameState();
}

class _MemoryGameState extends State<MemoryGame> {
  List<String> cards = [];
  final opened = <int>[];
  final matched = <int>{};
  int attempts = 0;
  Timer? timer;
  @override
  void initState() {
    super.initState();
    reset();
  }

  void reset() {
    timer?.cancel();
    cards = ['🌷', '🌷', '🍊', '🍊', '🐱', '🐱', '🌳', '🌳']..shuffle();
    opened.clear();
    matched.clear();
    attempts = 0;
  }

  void flip(int index) {
    if (opened.length == 2 ||
        opened.contains(index) ||
        matched.contains(index)) {
      return;
    }
    setState(() {
      opened.add(index);
      if (opened.length == 2) {
        attempts++;
        if (cards[opened[0]] == cards[opened[1]]) {
          matched.addAll(opened);
          opened.clear();
        } else {
          timer = Timer(const Duration(milliseconds: 1100), () {
            if (mounted) setState(opened.clear);
          });
        }
      }
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('같은 그림 찾기')),
    body: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text(
          matched.length == 8 ? '모두 찾았어요! 잘하셨어요.' : '같은 그림 두 장을 찾아요.',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 12),
        Text('찾은 그림 ${matched.length ~/ 2}쌍 / 4쌍 · 시도 $attempts번'),
        const SizedBox(height: 25),
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: cards.length,
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2,
            crossAxisSpacing: 12,
            mainAxisSpacing: 12,
            childAspectRatio: 1.6,
          ),
          itemBuilder: (_, index) {
            final visible = opened.contains(index) || matched.contains(index);
            return Semantics(
              label: visible ? '그림 ${cards[index]}' : '${index + 1}번째 카드 뒤집기',
              button: true,
              child: Material(
                color: matched.contains(index)
                    ? const Color(0xFFDEECD9)
                    : visible
                    ? Colors.white
                    : green,
                borderRadius: BorderRadius.circular(18),
                child: InkWell(
                  borderRadius: BorderRadius.circular(18),
                  onTap: () => flip(index),
                  child: Center(
                    child: Text(
                      visible ? cards[index] : '?',
                      style: const TextStyle(
                        fontSize: 36,
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ),
              ),
            );
          },
        ),
        const SizedBox(height: 24),
        OutlinedButton(
          onPressed: () => setState(reset),
          child: const Text('새로 시작하기'),
        ),
      ],
    ),
  );
}
