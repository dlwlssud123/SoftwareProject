import 'package:flutter/material.dart';
import '../data/demo_repository.dart';
import '../models/recommendations.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'profile_form.dart';
import 'recommendation_results.dart';

class MealScreen extends StatelessWidget {
  const MealScreen({
    required this.repository,
    required this.settings,
    super.key,
  });
  final DemoRepository repository;
  final AppSettings settings;
  void start(
    BuildContext context, {
    bool welfare = false,
    MealTime time = MealTime.lunch,
  }) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ProfileForm(
          repository: repository,
          settings: settings,
          welfare: welfare,
          initialTime: time,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(16, 10, 16, 24),
    children: [
      FeatureTile(
        key: const Key('meal-start'),
        title: '식생활 서비스',
        subtitle: '내 정보에 맞는 식단을 추천받아요',
        icon: Icons.restaurant_rounded,
        color: const Color(0xFFB85A00),
        background: const Color(0xFFFFF7E9),
        onTap: () => start(context),
      ),
      Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border.all(color: line),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(
                  Icons.play_circle_fill_rounded,
                  color: Color(0xFFE34135),
                  size: 28,
                ),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '오늘의 메뉴 추천',
                    style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 7),
            const Text(
              '식사 시간을 선택해 주세요.',
              style: TextStyle(fontSize: 15, color: muted),
            ),
            const SizedBox(height: 14),
            ServiceGrid(
              children: [
                for (final time in MealTime.values)
                  ServiceButton(
                    key: Key('meal-time-${time.name}'),
                    title: '${time.label} 메뉴',
                    icon: [
                      Icons.wb_sunny_rounded,
                      Icons.restaurant_rounded,
                      Icons.nightlight_round,
                      Icons.local_cafe_rounded,
                    ][time.index],
                    background: [
                      const Color(0xFFFBC52B),
                      const Color(0xFF258B43),
                      const Color(0xFF146CD7),
                      const Color(0xFFBD5200),
                    ][time.index],
                    foreground: time == MealTime.breakfast
                        ? const Color(0xFF3D3000)
                        : Colors.white,
                    onTap: () => start(context, time: time),
                  ),
              ],
            ),
          ],
        ),
      ),
      const SizedBox(height: 14),
      FeatureTile(
        key: const Key('welfare-start'),
        title: '복지 추천',
        subtitle: '내 조건에 맞는 복지 서비스를 찾아요',
        icon: Icons.campaign_rounded,
        color: const Color(0xFFCE4149),
        background: const Color(0xFFFFF1F1),
        onTap: () => start(context, welfare: true),
      ),
      const SectionTitle('레시피 살펴보기'),
      if (repository.recipes.isNotEmpty)
        FeatureTile(
          title: repository.recipes.first.name,
          subtitle: '재료와 조리 방법 보기',
          icon: Icons.menu_book_outlined,
          color: const Color(0xFFB85A00),
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => RecipeDetail(
                recipe: repository.recipes.first,
                settings: settings,
              ),
            ),
          ),
        ),
      const SizedBox(height: 8),
      const Text(
        '식품안전나라 API 데이터 · 추천 규칙은 발표용 예시',
        style: TextStyle(fontSize: 13, color: muted),
      ),
    ],
  );
}
