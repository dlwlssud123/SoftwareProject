import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/screens/nutrition_screen.dart';
import 'package:valueflow/screens/recommendation_results.dart';
import 'package:valueflow/models/recommendations.dart';

Future<void> launchApp(
  WidgetTester tester,
  DemoRepository repository, {
  AppSettings? settings,
}) async {
  tester.view.physicalSize = const Size(430, 932);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ValueFlowApp(repository: repository, settings: settings ?? AppSettings()),
  );
  await tester.pumpAndSettle();
}

Future<void> tap(WidgetTester tester, String key) async {
  await tester.tap(find.byKey(Key(key)));
  await tester.pumpAndSettle();
}

Future<void> completeForm(WidgetTester tester) async {
  await tap(tester, 'sample-fill');
  await tap(tester, 'profile-next');
  await tester.scrollUntilVisible(
    find.byKey(const Key('profile-consent')),
    220,
    scrollable: find
        .descendant(
          of: find.byKey(const Key('profile-scroll')),
          matching: find.byType(Scrollable),
        )
        .first,
  );
  await tester.pumpAndSettle();
  await tap(tester, 'profile-consent');
  await tap(tester, 'recommend-submit');
  await tester.pump(const Duration(milliseconds: 600));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  WidgetController.hitTestWarningShouldBeFatal = true;
  late DemoRepository repository;
  setUpAll(() async => repository = await DemoRepository.load());

  testWidgets('tabs mount on demand and retain their navigation stack', (
    tester,
  ) async {
    await launchApp(tester, repository);
    expect(find.byType(NutritionScreen, skipOffstage: false), findsNothing);
    await tap(tester, 'meal-start');
    await tester.enterText(find.byKey(const Key('profile-age')), '73');
    await tap(tester, 'tab-1');
    expect(find.byType(NutritionScreen), findsOneWidget);
    final inactiveForm = find.byKey(
      const Key('profile-age'),
      skipOffstage: false,
    );
    expect(TickerMode.valuesOf(tester.element(inactiveForm)).enabled, isFalse);
    await tap(tester, 'tab-0');
    expect(
      tester
          .widget<TextFormField>(find.byKey(const Key('profile-age')))
          .controller!
          .text,
      '73',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('empty and out-of-range ages cannot advance', (tester) async {
    await launchApp(tester, repository);
    await tap(tester, 'meal-start');
    await tap(tester, 'profile-next');
    expect(find.text('나이를 20~120세 사이로 입력해 주세요.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('profile-age')), '150');
    await tap(tester, 'profile-next');
    expect(find.byKey(const Key('recommend-submit')), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('meal presentation reaches personalized sample results', (
    tester,
  ) async {
    await launchApp(tester, repository);
    await tap(tester, 'meal-start');
    await completeForm(tester);
    expect(find.byType(AppBar), findsOneWidget);
    expect(find.byKey(const Key('recipe-results')), findsOneWidget);
    expect(find.text('김영희님을 위한\n점심 레시피'), findsOneWidget);
    expect(find.text('순두부 사과 소스 오이무침'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('recommend-submit')), findsOneWidget);
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('meal-start')), findsOneWidget);
  });

  testWidgets('welfare presentation reaches condition-specific examples', (
    tester,
  ) async {
    await launchApp(tester, repository, settings: AppSettings(textScale: 1.4));
    await tester.ensureVisible(find.byKey(const Key('welfare-start')));
    await tap(tester, 'welfare-start');
    await completeForm(tester);
    expect(find.byKey(const Key('welfare-results')), findsOneWidget);
    expect(find.text('김영희님을 위한\n복지 서비스'), findsOneWidget);
    expect(find.text('추천 서비스 6개'), findsOneWidget);
    expect(find.text('맞춤 복지 · 공공데이터'), findsOneWidget);
    await tester.ensureVisible(find.text('지원 대상과 혜택 보기').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('지원 대상과 혜택 보기').first);
    await tester.pumpAndSettle();
    expect(find.text('지원 대상'), findsOneWidget);
    expect(find.text('선정 기준'), findsOneWidget);
    expect(find.text('지원 내용'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('all five tabs and large type render without overflow', (
    tester,
  ) async {
    final settings = AppSettings();
    await launchApp(tester, repository, settings: settings);
    await settings.setScale(1.4);
    await tester.pumpAndSettle();
    for (var i = 0; i < 5; i++) {
      await tap(tester, 'tab-$i');
      expect(tester.takeException(), isNull, reason: 'tab $i at 140% font');
    }
    await tap(tester, 'settings-button');
    expect(find.text('음성 안내 사용'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  for (final scale in [1.0, 1.4]) {
    testWidgets('recipe detail shows every original step at $scale scale', (
      tester,
    ) async {
      final settings = AppSettings(textScale: scale);
      final recipe = repository.recipes.singleWhere((r) => r.id == '33');
      await launchApp(tester, repository, settings: settings);
      Navigator.of(tester.element(find.byKey(const Key('meal-start')))).push(
        MaterialPageRoute<void>(
          builder: (_) => RecipeDetail(recipe: recipe, settings: settings),
        ),
      );
      await tester.pumpAndSettle();
      final scrollable = find.descendant(
        of: find.byKey(const Key('recipe-detail-scroll')),
        matching: find.byType(Scrollable),
      );
      final warning = find.text('원본 데이터에 1·4단계가 없어 제공된 단계만 표시해요.');
      await tester.scrollUntilVisible(warning, 250, scrollable: scrollable);
      await tester.pumpAndSettle();
      expect(warning, findsOneWidget);
      for (var i = 0; i < recipe.steps.length; i++) {
        await tester.scrollUntilVisible(
          find.byKey(Key('recipe-step-$i')),
          200,
          scrollable: scrollable,
        );
        await tester.pumpAndSettle();
        final text = find.text(recipe.steps[i]);
        expect(text, findsOneWidget);
        expect(tester.widget<Text>(text).maxLines, isNull);
        expect(tester.takeException(), isNull);
      }
      expect(find.text('다음 단계'), findsNothing);
    });
  }

  testWidgets('recipe without cooking steps displays an empty state', (
    tester,
  ) async {
    final settings = AppSettings();
    final recipe = Recipe.fromPublicData({
      'RCP_SEQ': '28',
      'RCP_NM': '조리 정보 없음',
      'RCP_PARTS_DTLS': '준비할 재료',
      'RCP_WAY2': '찌기',
    });
    await launchApp(tester, repository, settings: settings);
    Navigator.of(tester.element(find.byKey(const Key('meal-start')))).push(
      MaterialPageRoute<void>(
        builder: (_) => RecipeDetail(recipe: recipe, settings: settings),
      ),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('원본 데이터에 조리 방법이 제공되지 않았어요.'),
      250,
      scrollable: find.descendant(
        of: find.byKey(const Key('recipe-detail-scroll')),
        matching: find.byType(Scrollable),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, '한 단계씩 따라 만들기'),
          )
          .onPressed,
      isNull,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('ingredient groups and long quantities wrap at 140% font', (
    tester,
  ) async {
    final settings = AppSettings(textScale: 1.4);
    final recipe = repository.recipes.singleWhere((r) => r.id == '32');
    await launchApp(tester, repository, settings: settings);
    Navigator.of(tester.element(find.byKey(const Key('meal-start')))).push(
      MaterialPageRoute<void>(
        builder: (_) => RecipeDetail(recipe: recipe, settings: settings),
      ),
    );
    await tester.pumpAndSettle();
    final scrollable = find.descendant(
      of: find.byKey(const Key('recipe-detail-scroll')),
      matching: find.byType(Scrollable),
    );
    await tester.scrollUntilVisible(
      find.text('오이무침'),
      250,
      scrollable: scrollable,
    );
    await tester.pumpAndSettle();
    expect(find.text('오이'), findsOneWidget);
    expect(find.text('70g(1/3개)'), findsOneWidget);
    expect(find.text('순두부사과 소스'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('50g(1/3개)'),
      200,
      scrollable: scrollable,
    );
    await tester.pumpAndSettle();
    expect(find.text('사과'), findsOneWidget);
    expect(find.text('50g(1/3개)'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
