import 'package:flutter/material.dart';

import '../core/network/api_exception.dart';
import '../data/recipe_library_api.dart';
import '../models/shopping_list.dart';
import '../widgets/async_state_view.dart';
import '../widgets/common.dart';

class ShoppingListScreen extends StatefulWidget {
  const ShoppingListScreen({
    required this.library,
    required this.date,
    super.key,
  });
  final RecipeLibraryApi library;
  final DateTime date;

  @override
  State<ShoppingListScreen> createState() => _ShoppingListScreenState();
}

class _ShoppingListScreenState extends State<ShoppingListScreen> {
  late Future<ShoppingListData> _list = widget.library.shopping(widget.date);
  String? _saving;

  void _load() => setState(() {
    _list = widget.library.shopping(widget.date);
  });

  Future<void> _toggle(ShoppingListData list, ShoppingItem item) async {
    setState(() => _saving = item.key);
    try {
      await widget.library.setShoppingChecked(widget.date, item, !item.checked);
      if (!mounted) return;
      setState(() {
        _list = Future.value(list.withChecked(item.key, !item.checked));
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      showMessage(context, error.message);
      if (error.statusCode == 409 || error.statusCode == 404) _load();
    } finally {
      if (mounted) setState(() => _saving = null);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('장보기 목록'),
      actions: [
        IconButton(
          tooltip: '장보기 목록 새로고침',
          onPressed: _saving == null ? _load : null,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: FutureBuilder<ShoppingListData>(
      future: _list,
      builder: (context, snapshot) => AsyncStateView(
        loading: snapshot.connectionState != ConnectionState.done,
        error: snapshot.error as ApiException?,
        onRetry: _load,
        isEmpty: false,
        builder: (context) {
          final list = snapshot.data!;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(
                MaterialLocalizations.of(context).formatFullDate(widget.date),
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 12),
              const Notice('식단에 담은 메뉴를 한 번씩 만들 때의 재료예요. 인분에 맞춰 자동으로 조절하지 않아요.'),
              const SizedBox(height: 12),
              for (final warning in list.warnings) ...[
                Notice(warning),
                const SizedBox(height: 12),
              ],
              if (list.items.isEmpty)
                const Notice(
                  '식단에 메뉴를 담으면 재료가 보여요. 담은 메뉴에 재료 정보가 없는 경우에는 레시피를 확인해 주세요.',
                )
              else
                SectionTitle(
                  '준비한 재료 ${list.items.where((item) => item.checked).length}/${list.items.length}',
                ),
              for (final item in list.items)
                Card(
                  margin: const EdgeInsets.only(bottom: 16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      CheckboxListTile(
                        key: Key('shopping-check-${item.key}'),
                        value: item.checked,
                        controlAffinity: ListTileControlAffinity.leading,
                        onChanged: _saving == null
                            ? (_) => _toggle(list, item)
                            : null,
                        title: Text(
                          item.name,
                          style: const TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        subtitle: Text(
                          _saving == item.key ? '체크 저장 중이에요' : item.amountText,
                          style: const TextStyle(fontSize: 18),
                        ),
                      ),
                      if (item.shoppingUrl case final url?)
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          child: OutlinedButton.icon(
                            key: Key('shopping-link-${item.key}'),
                            onPressed: () => openLink(context, url),
                            icon: const Icon(Icons.open_in_new),
                            label: const Text('쿠팡에서 재료 찾기'),
                            style: OutlinedButton.styleFrom(
                              minimumSize: const Size(48, 48),
                            ),
                          ),
                        ),
                      ExpansionTile(
                        title: const Text('메뉴별 원문 분량 보기'),
                        children: [
                          for (final source in item.sources)
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                              child: Align(
                                alignment: Alignment.centerLeft,
                                child: Text(
                                  '${source.mealLabel} · ${source.recipeName}\n${source.description}',
                                  style: const TextStyle(fontSize: 16),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              if (list.items.isNotEmpty)
                const Notice('구매는 쿠팡에서 직접 진행해 주세요. 가격·재고·배송비는 외부 페이지에서 확인해요.'),
            ],
          );
        },
      ),
    ),
  );
}
