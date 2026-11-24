import 'package:flutter/material.dart';
import '../models/shopping_link.dart';
import 'common.dart';

class IngredientShoppingButton extends StatelessWidget {
  const IngredientShoppingButton({
    required this.name,
    required this.url,
    super.key,
  });
  final String name;
  final Uri url;
  @override
  Widget build(BuildContext context) {
    if (ingredientShoppingUrl(url.toString(), name) == null) {
      return const SizedBox.shrink();
    }
    return OutlinedButton.icon(
      icon: const Icon(Icons.open_in_new),
      label: Text('$name 쿠팡에서 검색'),
      onPressed: () async {
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            scrollable: true,
            title: const Text('쿠팡에서 재료를 찾을까요?'),
            content: Text('$name 검색어만 외부 쿠팡에 보내요. 가격·재고·배송비는 쿠팡에서 확인해 주세요.'),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('취소'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('쿠팡으로 이동'),
              ),
            ],
          ),
        );
        if (confirmed == true && context.mounted) await openLink(context, url);
      },
    );
  }
}
