import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/models/recipe_ingredients.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'all 50 public recipes retain ingredient names and quantities',
    () async {
      final rows =
          jsonDecode(await rootBundle.loadString('assets/data/recipes.json'))
              as List<dynamic>;
      String content(String text) =>
          text.replaceAll(RegExp(r'[\s,，:：()（）\[\]●•·.]'), '');
      for (final row in rows) {
        final source = row['RCP_PARTS_DTLS'] as String;
        final groups = parseRecipeIngredients(source);
        final formatted = [
          for (final group in groups) ...[
            if (group.title != null) group.title!,
            for (final item in group.items) ...[
              item.name,
              if (item.quantity != null) item.quantity!,
            ],
          ],
        ].join();
        expect(content(formatted), content(source), reason: row['RCP_NM']);
      }
    },
  );

  test('groups ingredients and distinguishes names from quantities', () {
    final groups = parseRecipeIngredients(
      '●오이무침 :\n오이 70g(1/3개), 다진 땅콩 10g(1큰술)\n'
      '●순두부사과 소스 : \n순두부 40g(1/8봉지), 사과 50g(1/3개)',
    );
    expect(groups.map((g) => g.title), ['오이무침', '순두부사과 소스']);
    expect(groups.first.items.map((i) => i.name), ['오이', '다진 땅콩']);
    expect(groups.first.items.first.quantity, '70g(1/3개)');
    expect(groups.last.items.last.name, '사과');
    expect(groups.last.items.last.quantity, '50g(1/3개)');
  });

  test('commas inside preparation notes remain part of one ingredient', () {
    final groups = parseRecipeIngredients('닭고기(가슴살, 120g), 찹쌀(100g), 소금 약간');
    final items = groups.single.items;
    expect(items, hasLength(3));
    expect(items[0].name, '닭고기(가슴살, 120g)');
    expect(items[0].quantity, isNull);
    expect(items[1].name, '찹쌀');
    expect(items[1].quantity, '100g');
    expect(items[2].name, '소금');
    expect(items[2].quantity, '약간');
  });

  test('servings and inline stock or seasoning headings are retained', () {
    final groups = parseRecipeIngredients(
      '[1인분]부추 50g\n·양념장 : 간장 3g, 참깨 약간\n육수 물(300g)',
    );
    expect(groups.map((g) => g.title), ['1인분', '양념장', '육수']);
    expect(groups.last.items.single.name, '물');
    expect(groups.last.items.single.quantity, '300g');
  });

  test('unknown formats and unmatched parentheses never hide ingredients', () {
    expect(parseRecipeIngredients('마늘').single.items.single.name, '마늘');
    final groups = parseRecipeIngredients('후춧가루(0.5g\n두부(50g)');
    expect(groups.single.items.map((i) => i.name), ['후춧가루(0.5g', '두부']);
    expect(groups.single.items.last.quantity, '50g');
    expect(parseRecipeIngredients(' \n '), isEmpty);
  });
}
