import 'dart:async';
import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/services/usage_recorder.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/screens/settings_screen.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/data/demo_repository.dart';

void main() {
  late DemoRepository repository;
  setUpAll(() async => repository = await DemoRepository.load());
  late bool enabled;
  late String? owner;
  late UsageRecorder recorder;
  late List<List<Map<String, Object?>>> sent;
  setUp(() {
    enabled = false;
    owner = 'fixture-session';
    sent = [];
    recorder = UsageRecorder(
      enabled: () => enabled,
      token: () => owner,
      delay: const Duration(days: 1),
      send: (batch, token) async {
        sent.add(batch);
      },
    );
    UsageRecorder.current = recorder;
  });
  tearDown(() => recorder.dispose());

  test('collection is opt-in, bounded, batched and memory-only', () async {
    recorder.record('screen_view', 'meal');
    await recorder.flush();
    expect(sent, isEmpty);
    enabled = true;
    for (var i = 0; i < 130; i++) {
      recorder.record('screen_view', 'meal');
    }
    expect(recorder.pendingCount, 100);
    await recorder.flush();
    expect(sent.single.length, 20);
    expect(recorder.pendingCount, 80);
    expect(sent.single.map((e) => e['event_id']).toSet().length, 20);
    expect(
      sent.single.every(
        (e) => RegExp(r'^[0-9a-f-]{36}$').hasMatch(e['event_id'] as String),
      ),
      isTrue,
    );
    enabled = false;
    recorder.changed();
    expect(recorder.pendingCount, 0);
    await recorder.flush();
    expect(sent.length, 1);
  });

  test(
    'account changes and opt-out discard queued records without creating sessions',
    () async {
      enabled = true;
      recorder.record('screen_view', 'meal');
      owner = 'second-fixture-session';
      recorder.changed();
      expect(recorder.pendingCount, 0);
      recorder.record('screen_view', 'nutrition');
      await recorder.flush();
      expect(sent.single.single['feature'], 'nutrition');
      recorder.record('screen_view', 'settings');
      owner = null;
      await recorder.flush();
      expect(recorder.pendingCount, 0);
    },
  );

  test(
    'failed telemetry uploads are dropped and cannot fail app actions',
    () async {
      recorder.dispose();
      enabled = true;
      recorder = UsageRecorder(
        enabled: () => enabled,
        token: () => owner,
        delay: const Duration(days: 1),
        send: (_, _) async {
          throw StateError('transport failed');
        },
      );
      recorder.record('screen_view', 'meal');
      await recorder.flush();
      expect(recorder.pendingCount, 0);
    },
  );

  test(
    'route mapping discards IDs, queries, secrets and unknown endpoints',
    () {
      expect(
        usageRoute('/api/v1/recipes/private-recipe?q=private-query', 'GET'),
        ('recipes', 'view'),
      );
      expect(usageRoute('/api/v1/meals/private-id?version=1', 'DELETE'), (
        'nutrition',
        'delete',
      ));
      expect(usageRoute('/api/v1/usage-events', 'POST'), isNull);
      expect(usageRoute('/api/v1/auth/kakao', 'POST'), isNull);
      expect(usageRoute('/api/v1/profile', 'PUT'), isNull);
      expect(usageRoute('/private-health', 'POST'), isNull);
    },
  );

  test(
    'transport records only counters and UUID request ID, never request or response text',
    () async {
      enabled = true;
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      final client = ApiClient(dio: dio);
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (o, h) => h.resolve(
            Response(
              requestOptions: o,
              statusCode: 200,
              headers: Headers.fromMap({
                'x-request-id': ['12345678-1234-4234-8234-123456789abc'],
              }),
              data: {
                'data': {
                  'answer': 'private-answer',
                  'answer_status': 'generated',
                  'items': [
                    {'private': 'private-result'},
                  ],
                },
              },
            ),
          ),
        ),
      );
      await client.post(
        '/api/v1/ai/welfare-chat',
        body: {'message': 'private-question'},
        token: 'private-access-token',
        parse: (_) => true,
      );
      await recorder.flush();
      final text = jsonEncode(sent);
      expect(text, contains('request_started'));
      expect(text, contains('request_finished'));
      expect(text, contains('12345678-1234-4234-8234-123456789abc'));
      expect(text, contains('generated'));
      expect(text, isNot(contains('private-')));
      expect(sent.single.last['result_count'], 1);
    },
  );

  test('parsed response errors are recorded as a fixed category', () async {
    enabled = true;
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    final client = ApiClient(dio: dio);
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (o, h) => h.resolve(
          Response(
            requestOptions: o,
            statusCode: 200,
            data: {'data': 'private-response'},
          ),
        ),
      ),
    );
    await expectLater(
      client.get(
        '/api/v1/recipes',
        parse: (_) => throw const FormatException('private-error'),
      ),
      throwsA(isA<ApiException>()),
    );
    await recorder.flush();
    expect(sent.single.last['error_kind'], 'bad_response');
    expect(jsonEncode(sent), isNot(contains('private-')));
  });

  test(
    'responses from a previous account never appear under the next account',
    () async {
      enabled = true;
      final started = Completer<void>(), finish = Completer<void>();
      final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
      final client = ApiClient(dio: dio);
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (o, h) async {
            started.complete();
            await finish.future;
            h.resolve(Response(requestOptions: o, statusCode: 200, data: {}));
          },
        ),
      );
      final pending = client.get('/api/v1/recipes', parse: (_) => true);
      await started.future;
      owner = 'next-fixture-session';
      recorder.changed();
      finish.complete();
      await pending;
      await recorder.flush();
      expect(sent, isEmpty);
    },
  );

  testWidgets(
    'usage setting starts off and can be enabled and disabled without a forced dialog',
    (tester) async {
      final settings = AppSettings();
      expect(settings.usageSharing, isFalse);
      settings.addListener(recorder.changed);
      await tester.pumpWidget(
        MaterialApp(home: SettingsScreen(settings: settings)),
      );
      final toggle = find.byKey(const Key('usage-sharing'));
      await tester.ensureVisible(toggle);
      await tester.tap(toggle);
      await tester.pump();
      expect(settings.usageSharing, isTrue);
      await tester.tap(toggle);
      await tester.pump();
      expect(settings.usageSharing, isFalse);
    },
  );

  // Value: protects=timer batching, serialized flush and disposal;
  // fails_when=overlapping flush duplicates sends or dispose reschedules;
  // why_new=existing queue tests flush manually; seam=none;
  // no_claim=OS background delivery after process death.
  testWidgets('timer reschedules batches and serializes flush until disposal', (
    tester,
  ) async {
    recorder.dispose();
    enabled = true;
    final first = Completer<void>();
    recorder = UsageRecorder(
      enabled: () => enabled,
      token: () => owner,
      delay: const Duration(seconds: 1),
      send: (batch, _) async {
        sent.add(batch);
        if (sent.length == 1) await first.future;
      },
    );
    for (var i = 0; i < 41; i++) {
      recorder.record('screen_view', 'meal');
    }
    await tester.pump(const Duration(seconds: 1));
    expect(sent.map((batch) => batch.length), [20]);
    await recorder.flush();
    await tester.pump(const Duration(seconds: 5));
    expect(sent.length, 1);
    first.complete();
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(sent.map((batch) => batch.length), [20, 20]);
    expect(
      sent.expand((batch) => batch).map((e) => e['event_id']).toSet().length,
      40,
    );
    recorder.dispose();
    await tester.pump(const Duration(seconds: 5));
    await recorder.flush();
    expect(sent.length, 2);
    expect(recorder.pendingCount, 0);
  });

  // Value: protects=fixed failure metadata and caller error semantics;
  // fails_when=transport errors are recorded as success or private text is uploaded;
  // why_new=only parser failures were tested; seam=none;
  // no_claim=real network stack or server availability.
  test(
    'transport failure categories preserve caller outcomes without raw metadata',
    () async {
      enabled = true;
      final cases = [
        (
          DioExceptionType.connectionError,
          null,
          'network',
          ApiErrorType.network,
        ),
        (
          DioExceptionType.receiveTimeout,
          null,
          'timeout',
          ApiErrorType.timeout,
        ),
        (DioExceptionType.cancel, null, 'cancelled', ApiErrorType.cancelled),
        (
          DioExceptionType.badResponse,
          401,
          'unauthorized',
          ApiErrorType.badResponse,
        ),
        (
          DioExceptionType.badResponse,
          403,
          'forbidden',
          ApiErrorType.badResponse,
        ),
        (
          DioExceptionType.badResponse,
          409,
          'conflict',
          ApiErrorType.badResponse,
        ),
        (
          DioExceptionType.badResponse,
          422,
          'validation',
          ApiErrorType.badResponse,
        ),
        (DioExceptionType.badResponse, 500, 'server', ApiErrorType.server),
      ];
      for (final item in cases) {
        final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
        final client = ApiClient(dio: dio);
        dio.interceptors.add(
          InterceptorsWrapper(
            onRequest: (options, handler) {
              handler.reject(
                DioException(
                  requestOptions: options,
                  type: item.$1,
                  message: 'private-transport-error',
                  response: item.$2 == null
                      ? null
                      : Response(
                          requestOptions: options,
                          statusCode: item.$2,
                          data: {
                            'error': {'message': 'private-server-message'},
                          },
                        ),
                ),
              );
            },
          ),
        );
        await expectLater(
          client.get('/api/v1/recipes?query=private-query', parse: (_) => true),
          throwsA(
            isA<ApiException>()
                .having((e) => e.type, 'type', item.$4)
                .having((e) => e.statusCode, 'status', item.$2),
          ),
        );
        await recorder.flush();
        final finish = sent.last.last;
        expect(finish['event'], 'request_finished');
        expect(finish['error_kind'], item.$3);
        expect(
          finish['outcome'],
          item.$3 == 'cancelled' ? 'cancelled' : 'failure',
        );
        expect(finish['duration_ms'], isNonNegative);
      }
      expect(jsonEncode(sent), isNot(contains('private-')));
    },
  );

  // Value: protects=persisted opt-in and safe accessibility metadata;
  // fails_when=consent resets or settings/TTS leak user text;
  // why_new=existing toggle test uses nonpersistent settings; seam=none;
  // no_claim=device preferences durability or native speech engine.
  testWidgets(
    'consent persists and accessibility events contain only fixed metadata',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      final settings = await AppSettings.load();
      expect(settings.usageSharing, isFalse);
      recorder.dispose();
      recorder = UsageRecorder(
        enabled: () => settings.usageSharing,
        token: () => owner,
        delay: const Duration(days: 1),
        send: (batch, _) async {
          sent.add(batch);
        },
      );
      UsageRecorder.current = recorder;
      settings.addListener(recorder.changed);
      const channel = MethodChannel('flutter_tts');
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        (_) async => 1,
      );
      addTearDown(() {
        settings.removeListener(recorder.changed);
        tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          channel,
          null,
        );
        settings.dispose();
      });
      await settings.setUsageSharing(true);
      expect((await AppSettings.load()).usageSharing, isTrue);
      await settings.setScale(1.4);
      await settings.setVoice(false);
      await settings.setVoice(true);
      await settings.read('private-text-to-speak');
      await recorder.flush();
      expect(
        sent.single.map(
          (e) => (e['event'], e['setting_kind'], e['setting_value']),
        ),
        [
          ('setting_changed', 'text_size', 'largest'),
          ('setting_changed', 'voice', 'disabled'),
          ('setting_changed', 'voice', 'enabled'),
          ('read_aloud', null, null),
        ],
      );
      expect(jsonEncode(sent), isNot(contains('private-')));
      await settings.setUsageSharing(false);
      expect((await AppSettings.load()).usageSharing, isFalse);
      await settings.setScale(1.2);
      await recorder.flush();
      expect(sent.length, 1);
    },
  );

  // Value: protects=actual tab/lifecycle instrumentation and foreground exit flushing.
  testWidgets(
    'app shell reports tab changes and pause resume without reselect duplicates',
    (tester) async {
      enabled = true;
      await tester.pumpWidget(
        ValueFlowApp(
          repository: repository,
          settings: AppSettings(usageSharing: true),
        ),
      );
      await tester.pump();
      final initial = recorder.pendingCount;
      await tester.tap(find.byKey(const Key('tab-0')));
      await tester.pump();
      expect(recorder.pendingCount, initial);
      await tester.tap(find.byKey(const Key('tab-1')));
      await tester.pump();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      await recorder.flush();
      final events = sent.expand((batch) => batch).toList();
      expect(events.where((e) => e['event'] == 'app_open'), hasLength(1));
      expect(
        events
            .where((e) => e['event'] == 'screen_view')
            .map((e) => e['feature']),
        ['meal', 'nutrition', 'nutrition'],
      );
      expect(
        events
            .where((e) => e['event'] == 'screen_exit')
            .map((e) => e['feature']),
        ['meal', 'nutrition'],
      );
      expect(
        events
            .where((e) => e['event'] == 'screen_exit')
            .every((e) => (e['duration_ms'] as int) >= 0),
        isTrue,
      );
      await tester.pumpWidget(const SizedBox.shrink());
      recorder.dispose();
    },
  );

  // Value: protects=old navigation state cannot leak duration into a new account's events.
  testWidgets(
    'disposing the old account shell never attributes its duration to the new session',
    (tester) async {
      enabled = true;
      final settings = AppSettings(usageSharing: true);
      Widget shell(String key) => MaterialApp(
        home: AppShell(
          key: ValueKey(key),
          repository: repository,
          settings: settings,
        ),
      );
      await tester.pumpWidget(shell('first-account'));
      await tester.pump();
      await recorder.flush();
      sent.clear();
      owner = 'next-account-fixture';
      recorder.changed();
      await tester.pumpWidget(shell('next-account'));
      await tester.pump();
      await recorder.flush();
      final events = sent.expand((batch) => batch).toList();
      expect(events.where((e) => e['event'] == 'screen_exit'), isEmpty);
      expect(events.where((e) => e['event'] == 'app_open'), hasLength(1));
      await tester.pumpWidget(const SizedBox.shrink());
      recorder.dispose();
    },
  );
}
