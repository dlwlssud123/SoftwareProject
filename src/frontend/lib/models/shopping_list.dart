import 'shopping_link.dart';

class ShoppingSource {
  const ShoppingSource(this.mealLabel, this.recipeName, this.description);
  final String mealLabel, recipeName, description;

  factory ShoppingSource.fromJson(Map<String, dynamic> row) {
    const labels = {
      'breakfast': '아침',
      'lunch': '점심',
      'dinner': '저녁',
      'snack': '간식',
      'special': '특별 메뉴',
    };
    final label = labels[row['meal_slot']];
    if (label == null) throw const FormatException('Unknown meal slot');
    return ShoppingSource(
      label,
      row['recipe_name'] as String,
      [
        if ((row['section'] as String?)?.isNotEmpty == true) row['section'],
        row['name_raw'] as String,
        (row['amount_text'] as String?) ?? '분량 미제공',
      ].join(' '),
    );
  }
}

class ShoppingItem {
  const ShoppingItem({
    required this.key,
    required this.sourceHash,
    required this.name,
    required this.amountText,
    required this.checked,
    required this.sources,
    this.shoppingUrl,
  });
  final String key, sourceHash, name, amountText;
  final bool checked;
  final List<ShoppingSource> sources;
  final Uri? shoppingUrl;

  ShoppingItem withChecked(bool value) => ShoppingItem(
    key: key,
    sourceHash: sourceHash,
    name: name,
    amountText: amountText,
    checked: value,
    sources: sources,
    shoppingUrl: shoppingUrl,
  );

  factory ShoppingItem.fromJson(Map<String, dynamic> row) {
    final name = row['name'] as String;
    final url = ingredientShoppingUrl(row['shopping_search_url'], name);
    return ShoppingItem(
      key: row['item_key'] as String,
      sourceHash: row['source_hash'] as String,
      name: name,
      amountText: row['amount_text'] as String,
      checked: row['checked'] as bool,
      sources: [
        for (final source in row['sources'] as List)
          ShoppingSource.fromJson(source as Map<String, dynamic>),
      ],
      shoppingUrl: url,
    );
  }
}

class ShoppingListData {
  const ShoppingListData(this.items, this.warnings);
  final List<ShoppingItem> items;
  final List<String> warnings;

  ShoppingListData withChecked(String key, bool checked) => ShoppingListData([
    for (final item in items)
      item.key == key ? item.withChecked(checked) : item,
  ], warnings);

  factory ShoppingListData.fromJson(Map<String, dynamic> row) =>
      ShoppingListData([
        for (final item in row['items'] as List)
          ShoppingItem.fromJson(item as Map<String, dynamic>),
      ], (row['warnings'] as List).cast<String>());
}
