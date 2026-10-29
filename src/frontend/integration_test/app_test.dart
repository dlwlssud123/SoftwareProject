import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/services/settings.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Android presentation: recipe, welfare and every tab', (
    tester,
  ) async {
    final repository = await DemoRepository.load();
    final settings = AppSettings();
    await tester.pumpWidget(
      ValueFlowApp(repository: repository, settings: settings),
    );
    await tester.pumpAndSettle();
    await binding.convertFlutterSurfaceToImage();
    await tester.pumpAndSettle();

    Future<void> capture(String name) async {
      await tester.pumpAndSettle();
      await binding.takeScreenshot(name);
    }

    Future<void> tap(String key) async {
      await tester.tap(find.byKey(Key(key)));
      await tester.pumpAndSettle();
    }

    Future<void> completeForm(String prefix) async {
      await tap('sample-fill');
      await capture('$prefix-profile');
      await tap('profile-next');
      await tester.scrollUntilVisible(
        find.byKey(const Key('profile-consent')),
        200,
        scrollable: find
            .descendant(
              of: find.byKey(const Key('profile-scroll')),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      await tester.pumpAndSettle();
      await tap('profile-consent');
      await tap('recommend-submit');
      await tester.pump(const Duration(milliseconds: 700));
      await tester.pumpAndSettle();
    }

    await capture('01-home');
    await tap('meal-start');
    await completeForm('02-meal');
    expect(find.byKey(const Key('recipe-results')), findsOneWidget);
    await capture('03-meal-results');
    await tester.tap(find.text('순두부 사과 소스 오이무침'));
    await tester.pumpAndSettle();
    final detailScroll = find.descendant(
      of: find.byKey(const Key('recipe-detail-scroll')),
      matching: find.byType(Scrollable),
    );
    await tester.scrollUntilVisible(
      find.text('준비할 재료'),
      250,
      scrollable: detailScroll,
    );
    await tester.pumpAndSettle();
    expect(find.text('오이'), findsOneWidget);
    expect(find.text('70g(1/3개)'), findsOneWidget);
    await capture('03-meal-ingredients');
    await tester.scrollUntilVisible(
      find.text('조리 방법'),
      250,
      scrollable: detailScroll,
    );
    await tester.pumpAndSettle();
    await capture('03-meal-all-steps');
    final recipe = repository.recipes.singleWhere((r) => r.id == '32');
    await tester.scrollUntilVisible(
      find.text(recipe.steps.last),
      200,
      scrollable: detailScroll,
    );
    await tester.pumpAndSettle();
    expect(find.text(recipe.steps.last), findsOneWidget);
    expect(find.text('다음 단계'), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('welfare-start')));
    await tap('welfare-start');
    await completeForm('04-welfare');
    expect(find.byKey(const Key('welfare-results')), findsOneWidget);
    await capture('05-welfare-results');
    await tester.ensureVisible(find.text('지원 대상과 혜택 보기').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('지원 대상과 혜택 보기').first);
    await tester.pumpAndSettle();
    expect(find.text('지원 대상'), findsOneWidget);
    await capture('05-welfare-details');
    expect(tester.takeException(), isNull);

    for (var i = 1; i < 5; i++) {
      await tap('tab-$i');
      expect(tester.takeException(), isNull);
      await capture('tab-$i');
    }
    await tap('settings-button');
    await tester.tap(find.text('아주 크게'));
    await tester.pumpAndSettle();
    await capture('06-large-text');
    expect(tester.takeException(), isNull);
  });
}
