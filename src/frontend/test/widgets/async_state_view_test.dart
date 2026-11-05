import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/widgets/async_state_view.dart';

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('불러오는 중에는 진행 표시만 보인다', (tester) async {
    await tester.pumpWidget(
      _wrap(
        AsyncStateView(
          loading: true,
          isEmpty: false,
          builder: (_) => const Text('내용'),
        ),
      ),
    );
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('내용'), findsNothing);
  });

  testWidgets('재시도 가능한 오류는 다시 시도 버튼을 보여준다', (tester) async {
    var retried = 0;
    await tester.pumpWidget(
      _wrap(
        AsyncStateView(
          loading: false,
          isEmpty: false,
          error: const ApiException(ApiErrorType.network, '인터넷 연결을 확인해 주세요.'),
          onRetry: () => retried++,
          builder: (_) => const Text('내용'),
        ),
      ),
    );
    expect(find.text('인터넷 연결을 확인해 주세요.'), findsOneWidget);
    await tester.tap(find.text('다시 시도'));
    expect(retried, 1);
  });

  testWidgets('빈 결과면 안내 문구를 보여준다', (tester) async {
    await tester.pumpWidget(
      _wrap(
        AsyncStateView(
          loading: false,
          isEmpty: true,
          emptyMessage: '추천할 메뉴가 없어요',
          builder: (_) => const Text('내용'),
        ),
      ),
    );
    expect(find.text('추천할 메뉴가 없어요'), findsOneWidget);
  });

  testWidgets('데이터가 있으면 내용을 보여준다', (tester) async {
    await tester.pumpWidget(
      _wrap(
        AsyncStateView(
          loading: false,
          isEmpty: false,
          builder: (_) => const Text('내용'),
        ),
      ),
    );
    expect(find.text('내용'), findsOneWidget);
  });
}
