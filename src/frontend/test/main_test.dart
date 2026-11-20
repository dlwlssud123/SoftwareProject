import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/core/network/api_config.dart';
import 'package:valueflow/main.dart' as entry;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('앱 시작 시 서버 설정에 맞게 공통 계정과 주제 API를 연결한다', (tester) async {
    SharedPreferences.setMockInitialValues({});
    FlutterSecureStorage.setMockInitialValues({});
    await tester.runAsync(entry.main);
    await tester.pumpAndSettle();
    final app = tester.widget<ValueFlowApp>(find.byType(ValueFlowApp));
    if (ApiConfig.hasServer) {
      expect(app.account, isNotNull);
      expect(app.topicApi, isNotNull);
      expect(app.topicApi!.identity, same(app.account));
      expect(app.topicApi!.owner, isNull);
    } else {
      expect(app.account, isNull);
      expect(app.topicApi, isNull);
      await tester.tap(find.byKey(const Key('tab-3')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('playground-videos')));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('보고 싶은 주제 요청 · 내역'), 300);
      final button = tester.widget<OutlinedButton>(
        find.widgetWithText(OutlinedButton, '보고 싶은 주제 요청 · 내역'),
      );
      expect(button.onPressed, isNull);
    }
    expect(tester.takeException(), isNull);
  });
}
