class RecipeIngredient {
  const RecipeIngredient(this.name, [this.quantity]);
  final String name;
  final String? quantity;
}

class IngredientGroup {
  const IngredientGroup(this.title, this.items);
  final String? title;
  final List<RecipeIngredient> items;
}

List<IngredientGroup> parseRecipeIngredients(String source) {
  final groups = <IngredientGroup>[];
  String? title;
  var items = <RecipeIngredient>[];

  void finishGroup() {
    if (items.isNotEmpty) {
      groups.add(IngredientGroup(title, items));
    } else if (title != null) {
      groups.add(IngredientGroup(null, [RecipeIngredient(title)]));
    }
    items = [];
  }

  for (final rawLine in source.split(RegExp(r'\r?\n'))) {
    var line = rawLine.trim().replaceFirst(RegExp(r'^[●•·]\s*'), '');
    if (line.isEmpty) continue;
    final serving = RegExp(r'^\[([^\]]+)\]\s*').firstMatch(line);
    final heading = RegExp(r'^([^:：]+)[:：]\s*').firstMatch(line);
    final prefix = RegExp(
      r'^(고기완자양념|다시마육수|필수\s*재료|육수\s*재료|양념장|양념|육수|재료|완자)\s+',
    ).firstMatch(line);
    if (serving != null || heading != null || prefix != null) {
      final match = serving ?? heading ?? prefix!;
      finishGroup();
      title = match.group(1)!.trim();
      line = line.substring(match.end).trim();
    } else if (!RegExp(r'[\d,，(（]').hasMatch(line) &&
        !RegExp(r'약간|적당량|조금').hasMatch(line)) {
      finishGroup();
      title = line;
      continue;
    }

    // Commas inside quantities or preparation notes belong to one ingredient.
    var depth = 0;
    var start = 0;
    final entries = <String>[];
    for (var i = 0; i < line.length; i++) {
      final char = line[i];
      if (char == '(' || char == '（') depth++;
      if ((char == ')' || char == '）') && depth > 0) depth--;
      if ((char == ',' || char == '，') && depth == 0) {
        entries.add(line.substring(start, i));
        start = i + 1;
      }
    }
    entries.add(line.substring(start));

    for (final entry in entries) {
      final text = entry.trim();
      if (text.isEmpty) continue;
      final measured = RegExp(
        r'^([^()（）]+?)\s+(\d.*|약간|적당량|조금)$',
      ).firstMatch(text);
      final parenthesized = RegExp(
        r'^([^()（）]+)[(（](\d[^()（）]*)[)）]\.?$',
      ).firstMatch(text);
      final match = measured ?? parenthesized;
      // Keep unfamiliar formats intact rather than guessing a quantity.
      items.add(
        match == null
            ? RecipeIngredient(text)
            : RecipeIngredient(match.group(1)!.trim(), match.group(2)!.trim()),
      );
    }
  }
  finishGroup();
  return groups;
}
