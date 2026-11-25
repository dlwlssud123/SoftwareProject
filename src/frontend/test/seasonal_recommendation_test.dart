import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/models/recommendations.dart';
import 'package:valueflow/models/shopping_link.dart';
import 'package:valueflow/screens/recommendation_results.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/theme.dart';
import 'package:valueflow/widgets/ingredient_shopping_button.dart';

const _recipe = Recipe(
  id: '1',
  name: '시금치나물',
  ingredients: '시금치 100g',
  steps: [],
  calories: null,
  sodium: null,
  protein: null,
  carbs: null,
  fat: null,
  method: '',
  allergens: {},
  soft: false,
  fromServer: true,
);

Future<void> _pump(
  WidgetTester tester,
  List<SeasonalIngredient> seasonal, {
  double scale = 1,
}) async {
  tester.view.physicalSize = const Size(320, 900);
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
      home: RecipeDetail(
        recipe: _recipe,
        settings: AppSettings(),
        seasonal: seasonal,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _show(WidgetTester tester, Finder finder) async {
  final scroll = find
      .descendant(of: find.byType(ListView), matching: find.byType(Scrollable))
      .first;
  await tester.scrollUntilVisible(finder, 250, scrollable: scroll);
  await tester.pumpAndSettle();
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

void main() {
  WidgetController.hitTestWarningShouldBeFatal = true;
  test(
    'ingredient search accepts encoded names and rejects extra data and destinations',
    () {
      final good = Uri.https('www.coupang.com', '/np/search', {'q': '풋콩/껍질콩'});
      expect(ingredientShoppingUrl(good.toString(), '풋콩/껍질콩'), good);
      for (final bad in [
        'http://www.coupang.com/np/search?q=배',
        'https://www.coupang.com.evil.test/np/search?q=배',
        'https://www.coupang.com:8443/np/search?q=배',
        'https://www.coupang.com/vp/products/1?q=배',
        'https://www.coupang.com/np/search?q=사과',
        'https://www.coupang.com/np/search?q=배&q=사과',
        'https://www.coupang.com/np/search?q=배&profile=private',
        'https://www.coupang.com/np/search?q=배#fragment',
        'https://www.coupang.com/np/search?q=%FF',
      ]) {
        expect(ingredientShoppingUrl(bad, '배'), isNull, reason: bad);
      }
      final userInfo = Uri(
        scheme: 'https',
        host: 'www.coupang.com',
        userInfo: 'fixture',
        path: '/np/search',
        queryParameters: {'q': '배'},
      );
      expect(ingredientShoppingUrl(userInfo.toString(), '배'), isNull);
    },
  );

  testWidgets(
    'recommendation detail shows provided month and opens the exact official source',
    (tester) async {
      const channel = MethodChannel('plugins.flutter.io/url_launcher');
      final launched = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
        call,
      ) async {
        launched.add((call.arguments as Map)['url'] as String);
        expect((call.arguments as Map)['headers'], isEmpty);
        return true;
      });
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          channel,
          null,
        ),
      );
      final source = Uri.parse('https://www.nics.go.kr/food');
      await _pump(tester, [
        SeasonalIngredient('시금치', null, month: 11, sourceUrl: source),
      ]);
      await _show(tester, find.text('시금치 · 11월 재료'));
      expect(find.text('제철 재료와 출처'), findsOneWidget);
      await _show(tester, find.text('공식 제철 자료 보기'));
      await tester.tap(find.text('공식 제철 자료 보기'));
      await tester.pumpAndSettle();
      expect(launched, [source.toString()]);
      expect(find.text('레시피 살펴보기'), findsOneWidget);
    },
  );

  testWidgets('legacy evidence does not invent a month or source', (
    tester,
  ) async {
    await _pump(tester, [const SeasonalIngredient('시금치', null)]);
    await _show(tester, find.text('제철 재료와 출처'));
    // The ingredient list and the seasonal evidence each display the name.
    expect(find.text('시금치'), findsNWidgets(2));
    expect(find.textContaining('월 재료'), findsNothing);
    expect(find.text('공식 제철 자료 보기'), findsNothing);
    expect(find.byType(IngredientShoppingButton), findsNothing);
  });

  testWidgets(
    'shopping confirmation supports cancel and reports browser failure with large text',
    (tester) async {
      const channel = MethodChannel('plugins.flutter.io/url_launcher');
      final launched = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
        call,
      ) async {
        launched.add((call.arguments as Map)['url'] as String);
        expect((call.arguments as Map)['headers'], isEmpty);
        return false;
      });
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          channel,
          null,
        ),
      );
      final url = Uri.https('www.coupang.com', '/np/search', {'q': '시금치'});
      await _pump(tester, [
        SeasonalIngredient('시금치', url, month: 11),
      ], scale: 1.8);
      final button = find.text('시금치 쿠팡에서 검색');
      await _show(tester, button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(launched, isEmpty);
      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();
      expect(launched, isEmpty);
      await _show(tester, button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      await tester.tap(find.text('쿠팡으로 이동'));
      await tester.pumpAndSettle();
      expect(launched.length, 1);
      expect(Uri.parse(launched.single).queryParameters, {'q': '시금치'});
      expect(find.textContaining('연결할 수 없어요'), findsOneWidget);
      expect(find.text('레시피 살펴보기'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('invalid shopping URL never exposes a launch button', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: IngredientShoppingButton(
            name: '시금치',
            url: Uri.parse('https://www.coupang.com/np/search?q=다른재료'),
          ),
        ),
      ),
    );
    expect(find.byType(OutlinedButton), findsNothing);
  });
}
