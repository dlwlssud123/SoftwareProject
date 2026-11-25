import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/data/ai_api.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/data/intake_api.dart';
import 'package:valueflow/models/ai.dart';
import 'package:valueflow/screens/nutrition_screen.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/theme.dart';

class _Ai implements AiApi {
  int calls = 0;
  final response = Completer<PhotoRecognition>();

  @override
  Future<PhotoRecognition> photo(Uint8List bytes, CancelToken token) {
    calls++;
    return response.future;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Intake implements IntakeApi {
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('plugins.flutter.io/image_picker');
  late DemoRepository repository;
  late _Ai ai;
  late List<int> sources;
  String? pickedPath;
  setUpAll(() async => repository = await DemoRepository.load());
  setUp(() {
    sources = [];
    pickedPath = File('assets/images/95.png').absolute.path;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          expect(call.method, 'pickImage');
          sources.add((call.arguments as Map)['source'] as int);
          return pickedPath;
        });
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  Future<void> launch(WidgetTester tester, {double scale = 1}) async {
    ai = _Ai();
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        theme: appTheme(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: TextScaler.linear(scale)),
          child: child!,
        ),
        home: Scaffold(
          appBar: AppBar(title: const Text('영양분석')),
          body: NutritionScreen(
            repository: repository,
            settings: AppSettings(),
            aiApi: ai,
            intakeApi: _Intake(),
          ),
          bottomNavigationBar: const SizedBox(height: 64),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> choose(WidgetTester tester, String label) async {
    await tester.scrollUntilVisible(
      find.text(label),
      160,
      scrollable: find
          .descendant(
            of: find.byType(ListView).first,
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text(label));
    await tester.pumpAndSettle();
  }

  for (final (label, source) in [('사진 촬영하기', 0), ('앨범에서 선택하기', 1)]) {
    for (final scale in [1.0, 1.8]) {
      testWidgets(
        '$label immediately exposes action at 320px and text scale $scale',
        (tester) async {
          await launch(tester, scale: scale);
          expect(find.byKey(const Key('photo-analyze')), findsNothing);
          await choose(tester, label);
          expect(sources, [source]);
          final action = find.byKey(const Key('photo-analyze'));
          expect(action.hitTestable(), findsOneWidget);
          expect(
            find.descendant(of: action, matching: find.text('음식 찾기')),
            findsOneWidget,
          );
          expect(
            find.ancestor(of: action, matching: find.byType(ListView)),
            findsNothing,
          );
          expect(
            ai.calls,
            0,
            reason: 'Selecting a photo must not send it externally.',
          );
          expect(tester.takeException(), isNull);
        },
      );
    }
  }

  testWidgets(
    'canceling the picker leaves action hidden until a photo is chosen',
    (tester) async {
      pickedPath = null;
      await launch(tester);
      await choose(tester, '사진 촬영하기');
      expect(find.byKey(const Key('photo-analyze')), findsNothing);
      expect(ai.calls, 0);
      pickedPath = File('assets/images/95.png').absolute.path;
      await choose(tester, '앨범에서 선택하기');
      expect(
        find.byKey(const Key('photo-analyze')).hitTestable(),
        findsOneWidget,
      );
      pickedPath = null;
      await choose(tester, '다시 촬영하기');
      expect(
        find.byKey(const Key('photo-analyze')).hitTestable(),
        findsOneWidget,
      );
      expect(ai.calls, 0);
    },
  );

  testWidgets(
    'sticky action asks consent and prevents repeated recognition while waiting',
    (tester) async {
      await launch(tester);
      await choose(tester, '사진 촬영하기');
      final action = find.byKey(const Key('photo-analyze'));
      await tester.tap(action);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(ai.calls, 0);
      await tester.tap(find.text('동의하고 이용'));
      for (var attempt = 0; attempt < 20 && ai.calls == 0; attempt++) {
        await tester.pump(const Duration(milliseconds: 100));
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 10)),
        );
      }
      await tester.pump();
      expect(
        ai.calls,
        1,
        reason: tester
            .widgetList<Text>(find.byType(Text))
            .map((text) => text.data)
            .join('\n'),
      );
      expect(tester.widget<FilledButton>(action).onPressed, isNull);
      expect(find.text('음식을 찾고 있어요…').hitTestable(), findsOneWidget);
      ai.response.complete(const PhotoRecognition([], '사진에서 음식을 확인하지 못했어요.'));
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      expect(find.text('음식과 먹은 양 확인'), findsOneWidget);
      Navigator.of(tester.element(find.text('음식과 먹은 양 확인'))).pop();
      await tester.pumpAndSettle();
      expect(tester.widget<FilledButton>(action).onPressed, isNotNull);
      expect(tester.takeException(), isNull);
    },
  );
}
