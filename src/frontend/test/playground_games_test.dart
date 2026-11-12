import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/screens/playground_games.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/theme.dart';

Future<void> launchGame(WidgetTester tester, Widget game, double scale) async {
  tester.view.physicalSize = const Size(320, 640);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: appTheme(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(scale)),
        child: child!,
      ),
      home: game,
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> tapVisible(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isEmpty) {
    await tester.scrollUntilVisible(finder, 180);
  }
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
  expect(tester.takeException(), isNull);
}

const endings = {
  '가는 말이 고와야': '오는 말이 곱다',
  '낮말은 새가 듣고': '밤말은 쥐가 듣는다',
  '천 리 길도': '한 걸음부터',
  '호랑이도': '제 말 하면 온다',
  '세 살 버릇': '여든까지 간다',
  '콩 심은 데 콩 나고': '팥 심은 데 팥 난다',
  '발 없는 말이': '천 리 간다',
  '우물 안': '개구리',
};

void main() {
  WidgetController.hitTestWarningShouldBeFatal = true;
  late DemoRepository repository;
  setUpAll(() async => repository = await DemoRepository.load());

  for (final scale in [1.0, 1.4]) {
    testWidgets('numbers reject out of order, finish and restart at $scale', (
      tester,
    ) async {
      await launchGame(tester, const NumberOrderGame(), scale);
      await tapVisible(tester, find.byKey(const Key('number-3')));
      expect(find.text('다음 숫자 1'), findsOneWidget);
      expect(find.text('1부터 찾아볼까요? 천천히 눌러 주세요.'), findsOneWidget);
      for (var number = 1; number <= 9; number++) {
        await tapVisible(tester, find.byKey(Key('number-$number')));
        if (number < 9) {
          expect(
            tester
                .widget<OutlinedButton>(find.byKey(Key('number-$number')))
                .onPressed,
            isNull,
          );
          expect(find.text('다음 숫자 ${number + 1}'), findsOneWidget);
        }
      }
      expect(find.text('1부터 9까지 모두 찾았어요!'), findsOneWidget);
      await tapVisible(tester, find.text('다시 하기'));
      expect(find.text('다음 숫자 1'), findsOneWidget);
      expect(find.text('찾은 숫자 0 / 9'), findsOneWidget);
      for (var number = 1; number <= 9; number++) {
        expect(
          tester
              .widget<OutlinedButton>(find.byKey(Key('number-$number')))
              .onPressed,
          isNotNull,
        );
      }
    });

    testWidgets('proverbs score each question once and restart at $scale', (
      tester,
    ) async {
      await launchGame(tester, const ProverbGame(), scale);
      final seen = <String>{};
      for (var round = 0; round < 5; round++) {
        final beginning = tester
            .widget<Text>(find.byKey(const Key('proverb-question')))
            .data!;
        expect(seen.add(beginning), isTrue);
        final correct = endings[beginning]!;
        final correctRound = round.isEven;
        var choice = find.text(correct);
        if (!correctRound) {
          final button = tester.widget<OutlinedButton>(
            find.byKey(const Key('proverb-option-0')),
          );
          final first = (button.child! as Text).data;
          choice = first == correct
              ? find.byKey(const Key('proverb-option-1'))
              : find.byKey(const Key('proverb-option-0'));
        }
        await tapVisible(tester, choice);
        final feedback = find.text(
          correctRound ? '정답이에요!' : '정답은 ‘$correct’예요.',
        );
        await tester.scrollUntilVisible(feedback, 160);
        expect(feedback, findsOneWidget);
        // The chosen answer is locked before advancing to prevent double scoring.
        for (var option = 0; option < 3; option++) {
          final optionFinder = find.byKey(Key('proverb-option-$option'));
          await tester.ensureVisible(optionFinder);
          await tester.pumpAndSettle();
          expect(tester.widget<OutlinedButton>(optionFinder).onPressed, isNull);
        }
        final nextButton = find.byKey(const Key('proverb-next'));
        if (nextButton.evaluate().isEmpty) {
          await tester.scrollUntilVisible(nextButton, 180);
        }
        await tester.ensureVisible(nextButton);
        await tester.pumpAndSettle();
        await tester.tap(nextButton);
        await tester.tap(nextButton);
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      }
      expect(find.text('맞힌 속담 3 / 5개'), findsOneWidget);
      await tapVisible(tester, find.text('다시 하기'));
      expect(find.text('1 / 5 문제'), findsOneWidget);
      expect(find.text('정답이에요!'), findsNothing);
      expect(find.byKey(const Key('proverb-next')), findsNothing);
    });
  }

  testWidgets('both new games open from playground and return to it', (
    tester,
  ) async {
    await tester.pumpWidget(
      ValueFlowApp(
        repository: repository,
        settings: AppSettings(textScale: 1.4),
      ),
    );
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byKey(const Key('tab-4')));
    await tapVisible(tester, find.byKey(const Key('number-game-start')));
    expect(find.byType(NumberOrderGame), findsOneWidget);
    await tapVisible(tester, find.byType(BackButton));
    await tapVisible(tester, find.byKey(const Key('proverb-game-start')));
    expect(find.byType(ProverbGame), findsOneWidget);
    await tapVisible(tester, find.byType(BackButton));
    expect(find.byType(NumberOrderGame), findsNothing);
    expect(find.byType(ProverbGame), findsNothing);
    expect(find.byKey(const Key('proverb-game-start')), findsOneWidget);
  });
}
