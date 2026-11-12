import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/screens/playground_games.dart';
import 'package:valueflow/services/settings.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Android playground games with large text', (tester) async {
    final repository = await DemoRepository.load();
    await tester.pumpWidget(
      ValueFlowApp(
        repository: repository,
        settings: AppSettings(textScale: 1.4),
      ),
    );
    await tester.pumpAndSettle();
    await binding.convertFlutterSurfaceToImage();
    await tester.pumpAndSettle();

    Future<void> tap(Finder finder) async {
      await tester.ensureVisible(finder);
      await tester.pumpAndSettle();
      await tester.tap(finder);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    }

    await tap(find.byKey(const Key('tab-4')));
    await binding.takeScreenshot('playground-games');
    await tap(find.byKey(const Key('number-game-start')));
    expect(find.byType(NumberOrderGame), findsOneWidget);
    await binding.takeScreenshot('number-game');
    for (var number = 1; number <= 9; number++) {
      await tap(find.byKey(Key('number-$number')));
    }
    expect(find.text('1부터 9까지 모두 찾았어요!'), findsOneWidget);
    await binding.takeScreenshot('number-game-complete');
    await tap(find.text('놀이터로 돌아가기'));
    await tap(find.byKey(const Key('proverb-game-start')));
    expect(find.byType(ProverbGame), findsOneWidget);
    for (var round = 0; round < 5; round++) {
      await tap(find.byKey(const Key('proverb-option-0')));
      if (round == 0) await binding.takeScreenshot('proverb-game-answer');
      await tap(find.byKey(const Key('proverb-next')));
    }
    expect(find.text('속담 다섯 개를 함께 떠올렸어요!'), findsOneWidget);
    await tap(find.text('다시 하기'));
    expect(find.text('1 / 5 문제'), findsOneWidget);
    await tap(find.byType(BackButton));
    await tap(find.byKey(const Key('tab-0')));
    await tap(find.byKey(const Key('tab-4')));
    expect(find.byKey(const Key('proverb-game-start')), findsOneWidget);
  });
}
