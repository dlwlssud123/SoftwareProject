/// A public ingredient search only. Extra parameters must never carry profile
/// information, redirects, affiliate identifiers or a different search term.
Uri? ingredientShoppingUrl(Object? value, String name) {
  if (value is! String) return null;
  try {
    final uri = Uri.tryParse(value);
    return uri != null &&
            uri.scheme == 'https' &&
            uri.host == 'www.coupang.com' &&
            uri.userInfo.isEmpty &&
            uri.port == 443 &&
            uri.fragment.isEmpty &&
            uri.path == '/np/search' &&
            uri.queryParametersAll.length == 1 &&
            uri.queryParametersAll['q']?.length == 1 &&
            uri.queryParameters['q'] == name
        ? uri
        : null;
  } on FormatException {
    return null;
  }
}
