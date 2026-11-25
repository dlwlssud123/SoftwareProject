import 'package:flutter/material.dart';
import '../models/intake.dart';
import 'common.dart';

class IntakeEvidenceView extends StatelessWidget {
  const IntakeEvidenceView({
    required this.items,
    required this.contextInfo,
    super.key,
  });
  final List<FoodSelection> items;
  final AnalysisContext? contextInfo;
  static const methods = {
    'manual': '직접 고른 식품',
    'photo': '사진에서 찾은 음식',
    'similar_food': '비슷한 음식으로 대체',
    'ingredient_estimate': '예상 재료를 합산',
  };
  static const quantities = {
    'user_entered': '사용자가 입력한 양',
    'source_serving': 'DB 1회 분량 참고',
    'ai_estimate': 'AI가 예상한 양',
    'user_adjusted': '사용자가 바꾼 양',
  };
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      if (items.any((item) => item.estimated))
        const Notice('추정 분량이 포함된 참고값이에요. 실제 먹은 양을 측정한 값은 아니에요.'),
      if (items.any((item) => item.origin?.method == 'similar_food'))
        const Notice('비슷한 음식의 영양정보를 사용했어요. 재료·조리법에 따라 실제 영양과 다를 수 있어요.'),
      if (items.any((item) => item.origin?.method == 'ingredient_estimate'))
        const Notice('예상 재료의 영양을 합산했어요. 보이지 않는 기름·양념이 빠졌을 수 있어요.'),
      if (contextInfo?.partial == true)
        const Notice('제외한 재료가 있어 일부 영양이 합계에 포함되지 않아요.'),
      ExpansionTile(
        title: const Text('계산 기준과 제외한 재료'),
        children: [
          for (final item in items)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    '${item.food.name} · ${item.amount} ${item.unit}',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  Text('입력 방법: ${methods[item.origin?.method] ?? '기록 없음'}'),
                  if (item.origin?.recognizedName case final name?)
                    Text('처음 확인한 음식: $name'),
                  if (item.origin?.ingredientName case final name?)
                    Text('예상한 재료: $name'),
                  if (item.origin?.referenceRecipeName case final name?)
                    Text('입력 당시 참고 레시피: $name'),
                  Text(
                    '분량 기준: ${quantities[item.origin?.quantityBasis] ?? '기록 없음'}${item.estimated ? ' · 추정값' : ''}',
                  ),
                  Text('영양 자료 기준량: ${item.food.basisText ?? '기록 없음'}'),
                  Text(
                    '자료 출처: ${item.food.sourceProvider == 'data.go.kr:FoodNtrCpntDbInfo03'
                        ? '공공 식품영양성분 DB'
                        : item.food.sourceProvider == null
                        ? '기록 없음'
                        : '기록된 원천 자료'}',
                  ),
                  if (item.food.sourceCode case final code?)
                    Text('자료 식품 코드: $code'),
                ],
              ),
            ),
          if (contextInfo == null)
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text('제외한 재료 정보가 기록되지 않았어요.'),
            )
          else if (contextInfo!.excluded.isEmpty)
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text('기록된 제외 재료 없음'),
            )
          else
            for (final omitted in contextInfo!.excluded)
              Padding(
                padding: const EdgeInsets.all(12),
                child: Text(
                  '${omitted.dishName}: ${omitted.name} · ${omitted.reason == 'water'
                      ? '조리용 물 제외'
                      : omitted.reason == 'unmatched'
                      ? '연결하지 못해 제외'
                      : '사용자가 제외'}',
                ),
              ),
        ],
      ),
    ],
  );
}
