import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/auth_api.dart';
import 'package:valueflow/data/profile_api.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/data/topic_api.dart';
import 'package:valueflow/models/topic_request.dart';
import 'package:valueflow/screens/topic_screens.dart';
import 'package:valueflow/screens/assistant_screen.dart';
import 'package:valueflow/screens/content_screen.dart';
import 'package:valueflow/services/account.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/theme.dart';

const own = '00000000-0000-4000-8000-000000000001';
const other = '00000000-0000-4000-8000-000000000002';
const root = '/api/v1/content-topic-requests';
String identifier(int value) =>
    '00000000-0000-4000-8000-${value.toString().padLeft(12, '0')}';

class _Storage implements FlutterSecureStorage {
  final values = <String, String>{};
  bool failWrite = false, failDelete = false, failRead = false;
  Completer<void>? pauseDelete, deleteStarted;
  @override
  dynamic noSuchMethod(Invocation invocation) {
    final key = invocation.namedArguments[#key] as String;
    if (invocation.memberName == #read) {
      return failRead
          ? Future<String?>.error(PlatformException(code: 'read'))
          : Future<String?>.value(values[key]);
    }
    if (invocation.memberName == #write) {
      if (failWrite) {
        return Future<void>.error(PlatformException(code: 'write'));
      }
      values[key] = invocation.namedArguments[#value] as String;
      return Future<void>.value();
    }
    if (invocation.memberName == #delete) {
      if (failDelete) {
        return Future<void>.error(PlatformException(code: 'delete'));
      }
      final pause = pauseDelete;
      if (pause != null) {
        if (deleteStarted?.isCompleted == false) deleteStarted!.complete();
        return pause.future.then((_) {
          values.remove(key);
        });
      }
      values.remove(key);
      return Future<void>.value();
    }
    return super.noSuchMethod(invocation);
  }
}

class _Account extends Account {
  _Account(ApiClient client, _Storage storage)
    : super(
        AuthApi(client),
        storage,
        profiles: ProfileApi(client),
        serverUrl: 'https://example.test',
        kakaoEnabled: false,
      ) {
    change(own);
  }
  void change(String? user) {
    session = switch (user) {
      own => ServiceSession(
        userId: own,
        token: 'owner',
        expiresAt: DateTime.utc(2030),
        kakaoLinked: true,
      ),
      other => ServiceSession(
        userId: other,
        token: 'other',
        expiresAt: DateTime.utc(2030),
        kakaoLinked: true,
      ),
      null => null,
      _ => throw ArgumentError.value(user, 'user'),
    };
    entered = user != null;
    notifyListeners();
  }
}

class _Server {
  _Server() {
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    client = ApiClient(dio: dio);
    account = _Account(client, storage);
    api = TopicApi(
      client,
      account,
      storage,
      serverOrigin: 'https://example.test',
    );
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          requests.add(options);
          void fail(int status, String message) => handler.reject(
            DioException(
              requestOptions: options,
              type: DioExceptionType.badResponse,
              response: Response(
                requestOptions: options,
                statusCode: status,
                data: {
                  'error': {
                    'code': 'FIXTURE_ERROR',
                    'message': message,
                    'retryable': status >= 500,
                  },
                },
              ),
            ),
          );
          void network() => handler.reject(
            DioException(
              requestOptions: options,
              type: DioExceptionType.connectionError,
            ),
          );
          if (offline) {
            network();
            return;
          }
          final path = options.path;
          final user = switch (options.headers['Authorization']) {
            'Bearer owner' => own,
            'Bearer other' => other,
            _ => null,
          };
          final private = path.startsWith(root);
          if (private && (expire || user == null)) {
            fail(401, '다시 로그인해 주세요.');
            return;
          }
          Object? result;
          var status = 200;
          if (path == root && options.method == 'POST') {
            if (failBeforeSend) {
              network();
              return;
            }
            final body = Map<String, dynamic>.from(options.data as Map);
            final scope = '$user:${body['submission_id']}';
            var record = records[scope];
            final replayed = record != null;
            record ??= records[scope] = makeRecord(user!, body);
            if (loseAcknowledgement) {
              network();
              return;
            }
            result = {'request': public(record), 'replayed': replayed};
            status = replayed ? 200 : 201;
          } else if (path == '$root/withdraw-submission') {
            final body = Map<String, dynamic>.from(options.data as Map);
            final scope = '$user:${body['submission_id']}';
            final record = records.putIfAbsent(
              scope,
              () => makeRecord(user!, body),
            );
            record['status'] = 'withdrawn';
            record['topic'] = null;
            record['reply'] = null;
            record['guide'] = null;
            result = public(record);
          } else if (path == root) {
            final pause = pauseHistory;
            if (pause != null) await pause.future;
            var items = records.values
                .where((row) => row['_owner'] == user)
                .toList();
            final submission = options.queryParameters['submission_id'];
            if (submission != null) {
              items = items
                  .where((row) => row['_submission'] == submission)
                  .toList();
            }
            final offset = options.queryParameters['offset'] as int? ?? 0;
            result = {
              'items': items.skip(offset).take(20).map(public).toList(),
              'total': items.length,
              'offset': offset,
              'limit': 20,
            };
          } else if (private) {
            final id = path.split('/').last;
            final found = records.values.where(
              (row) => row['id'] == id && row['_owner'] == user,
            );
            if (found.isEmpty) {
              fail(404, '요청을 찾을 수 없어요.');
              return;
            }
            final record = found.single;
            if (options.method == 'DELETE') {
              record['status'] = 'withdrawn';
              record['topic'] = null;
              record['reply'] = null;
              record['guide'] = null;
            }
            result = public(record);
          } else if (path == '/api/v1/life-guides') {
            result = {
              'items': emptyGuides ? [] : [guide],
              'total': emptyGuides ? 0 : 1,
              'offset': options.queryParameters['offset'] ?? 0,
              'limit': 20,
            };
          } else if (path == '/api/v1/life-guides/phone-text') {
            if (goneGuide) {
              fail(404, '지금은 볼 수 없는 안내예요.');
              return;
            }
            result = {
              ...guide,
              'steps': List.generate(
                5,
                (index) => {
                  'title': '${index + 1}번째 안내',
                  'text': '설정에서 ${index + 1}번째 내용을 확인해요.',
                },
              ),
            };
          } else {
            fail(404, 'Unknown fixture route');
            return;
          }
          handler.resolve(
            Response(
              requestOptions: options,
              statusCode: status,
              data: {
                'data': result,
                'meta': {'request_id': identifier(99)},
              },
            ),
          );
        },
      ),
    );
  }
  final storage = _Storage();
  late final ApiClient client;
  late final _Account account;
  late final TopicApi api;
  final requests = <RequestOptions>[];
  final records = <String, Map<String, dynamic>>{};
  bool offline = false,
      failBeforeSend = false,
      loseAcknowledgement = false,
      expire = false,
      goneGuide = false,
      emptyGuides = false;
  Completer<void>? pauseHistory;
  final guide = <String, dynamic>{
    'id': identifier(50),
    'slug': 'phone-text',
    'title': '휴대폰 글씨 크게 보기',
    'source_reference': '팀 사용 안내',
    'checked_on': '2026-11-19',
  };
  Map<String, dynamic> makeRecord(String user, Map<String, dynamic> body) => {
    'id': identifier(records.length + 10),
    '_owner': user,
    '_submission': body['submission_id'],
    'kind': body['kind'],
    'topic': body['topic'],
    'status': 'received',
    'version': 1,
    'reply': null,
    'guide': null,
    'created_at': '2026-11-20T00:00:00Z',
    'updated_at': '2026-11-20T00:00:00Z',
  };
  Map<String, dynamic> public(Map<String, dynamic> row) => {
    for (final entry in row.entries)
      if (!entry.key.startsWith('_')) entry.key: entry.value,
  };
  int get sends => requests
      .where((request) => request.path == root && request.method == 'POST')
      .length;
  int get cancellations => requests
      .where((request) => request.path.endsWith('/withdraw-submission'))
      .length;
}

Widget page(Widget child, {double scale = 1}) => MaterialApp(
  theme: appTheme(),
  builder: (context, child) => MediaQuery(
    data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
    child: child!,
  ),
  home: child,
);
TopicRequestsScreen _requests(_Server server) =>
    TopicRequestsScreen(api: server.api, settings: AppSettings(voice: false));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('준비한 UUID는 재시작·동일 전송에도 유지되고 저장소는 서버·계정별로 나눈다', () async {
    final server = _Server();
    final pending = await server.api.prepare(TopicKind.lifeGuide, '글씨 크게 보기');
    expect(
      topicUuid(pending.submissionId, submission: true),
      pending.submissionId,
    );
    expect(
      (await server.api.prepare(
        TopicKind.lifeGuide,
        pending.topic,
      )).submissionId,
      pending.submissionId,
    );
    final restored = TopicApi(
      server.client,
      server.account,
      server.storage,
      serverOrigin: 'https://example.test',
    );
    expect((await restored.pending())!.submissionId, pending.submissionId);
    expect(server.storage.values.keys.single, contains(own));
    expect(
      jsonDecode(server.storage.values.values.single),
      pending.toStorage(),
    );
    expect(server.storage.values.values.single, isNot(contains('fixture-')));
    server.account.change(other);
    expect(await restored.pending(), isNull);
    await expectLater(server.api.submit(pending), throwsA(isA<ApiException>()));
    expect(server.sends, 0);
  });

  test('전송 전 보관 실패는 서버 전송을 시작하지 않는다', () async {
    final server = _Server()..storage.failWrite = true;
    await expectLater(
      server.api.prepare(TopicKind.video, '꽃 키우기'),
      throwsA(isA<ApiException>()),
    );
    expect(server.requests, isEmpty);
  });

  test('응답을 잃어도 읽기 조회로 접수를 확인하고 새 POST를 만들지 않는다', () async {
    final server = _Server()..loseAcknowledgement = true;
    final pending = await server.api.prepare(TopicKind.video, '산책 영상');
    await expectLater(server.api.submit(pending), throwsA(isA<ApiException>()));
    expect((await server.api.pending())!.submissionId, pending.submissionId);
    final restored = TopicApi(
      server.client,
      server.account,
      server.storage,
      serverOrigin: 'https://example.test',
    );
    final found = await restored.lookup(pending);
    expect(found!.topic, pending.topic);
    expect(server.sends, 1);
    expect(await restored.pending(), isNull);
  });

  test('접수 전 취소 후 늦게 전송해도 취소된 결과를 유지한다', () async {
    final server = _Server()..failBeforeSend = true;
    final pending = await server.api.prepare(TopicKind.video, '꽃 키우기');
    await expectLater(server.api.submit(pending), throwsA(isA<ApiException>()));
    expect(await server.api.lookup(pending), isNull);
    final cancelled = await server.api.cancelPending(pending);
    expect(cancelled.withdrawn, isTrue);
    server.failBeforeSend = false;
    final late = await server.api.submit(pending);
    expect(late.withdrawn, isTrue);
    expect(server.records.length, 1);
    expect(await server.api.pending(), isNull);
  });

  test('보내던 내용이 다르면 같은 전송 번호를 몰래 재사용하지 않는다', () async {
    final server = _Server();
    await server.api.prepare(TopicKind.video, '먼저 요청한 내용');
    await expectLater(
      server.api.prepare(TopicKind.lifeGuide, '바뀐 내용'),
      throwsA(isA<ApiException>()),
    );
    expect(server.sends, 0);
  });

  test('인증 만료 후에는 자동으로 새 게스트를 만들어 보내지 않는다', () async {
    final server = _Server()..expire = true;
    await expectLater(server.api.history(), throwsA(isA<ApiException>()));
    expect(server.account.session, isNull);
    await expectLater(
      server.api.prepare(TopicKind.video, '다른 내용'),
      throwsA(isA<ApiException>()),
    );
    expect(
      server.requests.any((request) => request.path.endsWith('/auth/guest')),
      isFalse,
    );
  });

  test('접수 후 기기 정리가 실패해도 확인된 요청 다음에는 새 번호를 만든다', () async {
    final server = _Server();
    final first = await server.api.prepare(TopicKind.video, '첫 번째 내용');
    server.storage.failDelete = true;
    await server.api.submit(first);
    expect((await server.api.pending())!.submissionId, first.submissionId);
    final next = await server.api.prepare(TopicKind.lifeGuide, '다음 내용');
    expect(next.submissionId, isNot(first.submissionId));
    expect((await server.api.pending())!.submissionId, next.submissionId);
    expect(server.sends, 1);
  });

  test('손상된 보관 정보의 줄바꿈은 전송 가능한 주제로 복원하지 않는다', () {
    final stored = PendingTopic(
      own,
      identifier(9),
      TopicKind.video,
      '첫 줄\n다음 줄',
    );
    expect(
      () => PendingTopic.fromStorage(stored.toStorage()),
      throwsFormatException,
    );
  });

  test('이전 접수의 느린 기기 정리가 다음 전송 번호를 지우지 않는다', () async {
    final server = _Server();
    final first = await server.api.prepare(TopicKind.video, '먼저 보낸 요청');
    server.storage.pauseDelete = Completer<void>();
    server.storage.deleteStarted = Completer<void>();
    final submitted = server.api.submit(first);
    await server.storage.deleteStarted!.future;
    final nextTask = server.api.prepare(TopicKind.lifeGuide, '다음 요청');
    server.storage.pauseDelete!.complete();
    await submitted;
    final next = await nextTask;
    expect(next.submissionId, isNot(first.submissionId));
    expect((await server.api.pending())!.submissionId, next.submissionId);
    expect(server.sends, 1);
  });

  test('다른 계정으로 바뀐 뒤 도착한 내역 응답을 거절한다', () async {
    final server = _Server()..pauseHistory = Completer<void>();
    final response = server.api.history();
    final assertion = expectLater(response, throwsA(isA<ApiException>()));
    await Future<void>.delayed(Duration.zero);
    server.account.change(other);
    server.pauseHistory!.complete();
    await assertion;
  });

  test('취소 응답의 원문·모르는 상태·시간대 없는 날짜는 정상 자료가 아니다', () {
    final server = _Server();
    final record = server.public(
      server.makeRecord(own, {
        'submission_id': identifier(3),
        'kind': 'video',
        'topic': '확인',
      }),
    );
    for (final change in [
      {'status': 'withdrawn'},
      {'status': 'other'},
      {'created_at': '2026-11-20T00:00:00'},
    ]) {
      expect(
        () => TopicRecord.fromJson({...record, ...change}),
        throwsFormatException,
      );
    }
  });

  testWidgets('주제 접수 성공 후 내역을 표시하고 상세 답변·가이드를 열 수 있다', (tester) async {
    final server = _Server();
    await tester.pumpWidget(page(_requests(server)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('topic-input')), '글씨 크게 보기');
    await tester.ensureVisible(find.byKey(const Key('send-topic')));
    await tester.tap(find.byKey(const Key('send-topic')));
    await tester.pumpAndSettle();
    expect(server.sends, 1);
    expect(find.text('요청을 접수했어요. 아래에서 답변을 확인해 주세요.'), findsOneWidget);
    final record = server.records.values.single;
    record['status'] = 'completed';
    record['reply'] = '안내를 준비했어요.';
    record['guide'] = server.guide;
    await tester.ensureVisible(find.text('글씨 크게 보기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('글씨 크게 보기'));
    await tester.pumpAndSettle();
    expect(find.text('안내를 준비했어요.'), findsOneWidget);
    await tester.tap(find.text('생활 안내 보기'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('5단계 · 5번째 안내'), 300);
    expect(find.text('설정에서 5번째 내용을 확인해요.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('서버 응답이 불명확하면 내용을 잠그고 같은 번호로 취소한다', (tester) async {
    final server = _Server()..failBeforeSend = true;
    await tester.pumpWidget(page(_requests(server)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('topic-input')), '바둑 영상');
    await tester.ensureVisible(find.byKey(const Key('send-topic')));
    await tester.tap(find.byKey(const Key('send-topic')));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<EditableText>(
            find.descendant(
              of: find.byKey(const Key('topic-input')),
              matching: find.byType(EditableText),
            ),
          )
          .readOnly,
      isTrue,
    );
    await tester.ensureVisible(find.text('보내던 요청 취소'));
    await tester.tap(find.text('보내던 요청 취소'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '요청 취소'));
    await tester.pumpAndSettle();
    expect(server.cancellations, 1);
    expect(find.text('요청을 취소했어요.'), findsOneWidget);
    expect(server.records.values.single['topic'], isNull);
  });

  testWidgets('보관 실패에서도 입력은 남고 POST는 전송되지 않는다', (tester) async {
    final server = _Server();
    await tester.pumpWidget(page(_requests(server)));
    await tester.pumpAndSettle();
    server.storage.failWrite = true;
    await tester.enterText(find.byKey(const Key('topic-input')), '유지할 주제');
    await tester.ensureVisible(find.byKey(const Key('send-topic')));
    await tester.tap(find.byKey(const Key('send-topic')));
    await tester.pumpAndSettle();
    expect(server.sends, 0);
    expect(find.text('유지할 주제'), findsOneWidget);
    expect(
      tester
          .widget<EditableText>(
            find.descendant(
              of: find.byKey(const Key('topic-input')),
              matching: find.byType(EditableText),
            ),
          )
          .readOnly,
      isFalse,
    );
  });

  testWidgets('계정 변경은 작성 내용과 이전 내역을 즉시 감춘다', (tester) async {
    final server = _Server();
    await tester.pumpWidget(page(_requests(server)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('topic-input')), '이전 계정의 내용');
    server.account.change(other);
    await tester.pumpAndSettle();
    expect(find.text('이전 계정의 내용'), findsNothing);
    expect(find.text('계정이 바뀌었어요. 화면을 닫고 다시 열어 주세요.'), findsOneWidget);
  });

  testWidgets('뒤로가기에서 미전송 글을 버릴지 확인하고 취소하면 유지한다', (tester) async {
    final server = _Server();
    await tester.pumpWidget(
      page(
        Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => _requests(server)),
              ),
              child: const Text('열기'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('열기'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('topic-input')), '보내기 전 글');
    await tester.pump();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('작성을 그만둘까요?'), findsOneWidget);
    await tester.tap(find.text('아니요'));
    await tester.pumpAndSettle();
    expect(find.text('보내기 전 글'), findsOneWidget);
    expect(server.sends, 0);
  });

  testWidgets('320px와 큰 글자에서도 요청 화면이 넘치지 않는다', (tester) async {
    tester.view.physicalSize = const Size(320, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final server = _Server();
    await tester.pumpWidget(page(_requests(server), scale: 1.8));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.scrollUntilVisible(
      find.text('내역 새로고침'),
      250,
      scrollable: find.byType(Scrollable).first,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('비공개가 된 안내는 예시 내용으로 대체하지 않고 재시도한다', (tester) async {
    final server = _Server()..goneGuide = true;
    final summary = GuideSummary.fromJson(server.guide);
    await tester.pumpWidget(
      page(
        GuideReaderScreen(
          api: server.api,
          settings: AppSettings(voice: false),
          summary: summary,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('지금은 볼 수 없는 안내예요.'), findsOneWidget);
    expect(find.text('설정에서 1번째 내용을 확인해요.'), findsNothing);
    server.goneGuide = false;
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(find.text('설정에서 1번째 내용을 확인해요.'), findsOneWidget);
  });

  testWidgets('이전 미확인 요청을 복원할 때 새로 보내지 않고 같은 번호로 재시도한다', (tester) async {
    final server = _Server();
    final pending = await server.api.prepare(TopicKind.video, '복원할 요청');
    await tester.pumpWidget(page(_requests(server)));
    await tester.pumpAndSettle();
    expect(server.sends, 0);
    expect(find.text('복원할 요청'), findsOneWidget);
    await tester.ensureVisible(find.text('같은 내용으로 보내기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('같은 내용으로 보내기'));
    await tester.pumpAndSettle();
    expect(server.sends, 1);
    expect(server.records.keys.single, '$own:${pending.submissionId}');
  });

  testWidgets('손상된 전송 정보는 내역을 확인하고 명시적으로 정리한다', (tester) async {
    final server = _Server();
    await server.api.prepare(TopicKind.video, '보관한 요청');
    server.storage.values.updateAll((_, _) => 'broken-json');
    await tester.pumpWidget(page(_requests(server)));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('send-topic')), findsNothing);
    expect(find.text('아직 보낸 요청이 없어요.'), findsOneWidget);
    await tester.tap(find.text('요청 내역 확인 후 전송 정보 정리'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('확인 후 정리'));
    await tester.pumpAndSettle();
    expect(server.storage.values, isEmpty);
    expect(find.byKey(const Key('send-topic')), findsOneWidget);
    expect(server.sends, 0);
  });

  testWidgets('접수된 요청 상세에서 취소하면 원문과 답변이 사라진다', (tester) async {
    final server = _Server();
    final row = server.makeRecord(own, {
      'submission_id': identifier(7),
      'kind': 'video',
      'topic': '취소할 내용',
    });
    server.records['$own:${identifier(7)}'] = row;
    await tester.pumpWidget(
      page(
        TopicDetailScreen(
          api: server.api,
          settings: AppSettings(voice: false),
          id: row['id'] as String,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('요청 취소'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '요청 취소'));
    await tester.pumpAndSettle();
    expect(find.text('취소한 요청'), findsOneWidget);
    expect(find.text('취소할 내용'), findsNothing);
    expect(server.records.values.single['topic'], isNull);
  });

  testWidgets('놀이터 영상의 요청 버튼은 서버 요청 화면을 영상으로 연다', (tester) async {
    final server = _Server();
    await tester.pumpWidget(
      page(
        Scaffold(
          body: ContentScreen(
            settings: AppSettings(voice: false),
            topicApi: server.api,
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('playground-videos')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('보고 싶은 주제 요청 · 내역'), 300);
    await tester.tap(find.text('보고 싶은 주제 요청 · 내역'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, '영상')).selected,
      isTrue,
    );
    expect(server.requests.any((r) => r.path == root), isTrue);
  });

  testWidgets('생활 도우미에서 게시 안내와 요청 내역을 연다', (tester) async {
    final server = _Server();
    await tester.pumpWidget(
      page(
        Scaffold(
          body: AssistantScreen(
            repository: const DemoRepository([], []),
            settings: AppSettings(voice: false),
            topicApi: server.api,
          ),
        ),
      ),
    );
    await tester.scrollUntilVisible(find.text('생활 도우미'), 300);
    await tester.tap(find.text('생활 도우미'));
    await tester.pumpAndSettle();
    expect(find.text('휴대폰 글씨 크게 보기'), findsOneWidget);
    await tester.tap(find.text('필요한 안내 요청 · 내역'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('topic-input')), findsOneWidget);
    expect(server.sends, 0);
  });

  testWidgets('다른 화면의 미확인 요청을 취소해도 새로 쓰던 글은 남는다', (tester) async {
    final server = _Server();
    await tester.pumpWidget(page(_requests(server)));
    await tester.pumpAndSettle();
    await server.api.prepare(TopicKind.video, '다른 화면에서 보낸 요청');
    await tester.enterText(find.byKey(const Key('topic-input')), '새로 쓰던 글');
    await tester.ensureVisible(find.byKey(const Key('send-topic')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('send-topic')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('보내던 요청 확인'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('보내던 요청 확인'));
    await tester.pumpAndSettle();
    expect(find.text('다른 화면에서 보낸 요청'), findsOneWidget);
    await tester.ensureVisible(find.text('보내던 요청 취소'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('보내던 요청 취소'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '요청 취소'));
    await tester.pumpAndSettle();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('새로 쓰던 글'), findsOneWidget);
    expect(server.sends, 0);
  });
}
