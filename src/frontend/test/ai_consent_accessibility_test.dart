import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/theme.dart';
import 'package:valueflow/widgets/ai_consent.dart';

void main() {
  for (final photo in [false, true]) {
    testWidgets(
      'AI consent stays usable at 320px with 180% text, photo=$photo',
      (tester) async {
        tester.view.physicalSize = const Size(320, 720);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        bool? allowed;
        await tester.pumpWidget(
          MaterialApp(
            theme: appTheme(),
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(
                context,
              ).copyWith(textScaler: const TextScaler.linear(1.8)),
              child: child!,
            ),
            home: Scaffold(
              body: Builder(
                builder: (context) => FilledButton(
                  onPressed: () async {
                    allowed = await confirmAiProcessing(context, photo: photo);
                  },
                  child: const Text('열기'),
                ),
              ),
            ),
          ),
        );
        await tester.tap(find.text('열기'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.text('동의하고 이용').hitTestable(), findsOneWidget);
        await tester.tap(find.text('동의하고 이용').hitTestable());
        await tester.pumpAndSettle();
        expect(allowed, isTrue);
      },
    );
  }
}
