import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/auth_api.dart';
import 'package:valueflow/data/community_api.dart';
import 'package:valueflow/data/profile_api.dart';
import 'package:valueflow/models/community.dart';
import 'package:valueflow/screens/community_screens.dart';
import 'package:valueflow/screens/content_screen.dart';
import 'package:valueflow/services/account.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/theme.dart';

String id(int n) => '00000000-0000-4000-8000-${n.toString().padLeft(12, '0')}';
const root = '/api/v1/community';

class _Storage implements FlutterSecureStorage {
  final values = <String, String>{};
  bool failWrite = false;
  @override
  dynamic noSuchMethod(Invocation invocation) {
    final key = invocation.namedArguments[#key] as String;
    if (invocation.memberName == #read) {
      return Future<String?>.value(values[key]);
    }
    if (invocation.memberName == #write) {
      if (failWrite) {
        return Future<void>.error(PlatformException(code: 'write'));
      }
      values[key] = invocation.namedArguments[#value] as String;
      return Future<void>.value();
    }
    if (invocation.memberName == #delete) {
      values.remove(key);
      return Future<void>.value();
    }
    return super.noSuchMethod(invocation);
  }
}

class _Server {
  _Server() {
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    client = ApiClient(dio: dio);
    account = Account(
      AuthApi(client),
      storage,
      profiles: ProfileApi(client),
      serverUrl: 'https://example.test',
      kakaoEnabled: false,
    );
    changeOwner(1);
    api = newApi();
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (request, handler) async {
          requests.add(request);
          void fail(int status) => handler.reject(
            DioException(
              requestOptions: request,
              type: DioExceptionType.badResponse,
              response: Response(
                requestOptions: request,
                statusCode: status,
                data: {
                  'error': {
                    'message': '요청을 다시 확인해 주세요.',
                    'retryable': status >= 500,
                  },
                },
              ),
            ),
          );
          if (denied) {
            fail(401);
            return;
          }
          if (paused != null) await paused!.future;
          Object? data;
          if (request.path == '$root/posts' && request.method == 'POST') {
            final body = request.data as Map;
            final key = body['submission_id'] as String;
            final replay = submitted.containsKey(key);
            final row = submitted.putIfAbsent(
              key,
              () => post(
                10,
                mine: true,
                title: body['title'] as String,
                text: body['body'] as String,
              ),
            );
            data = {'post': row, 'replayed': replay};
            if (loseResponse) {
              loseResponse = false;
              fail(503);
              return;
            }
          } else if (request.path == '$root/posts/mine' ||
              request.path == '$root/posts') {
            data = page(
              request.path.endsWith('mine')
                  ? submitted.values.toList()
                  : blocked
                  ? []
                  : [post(2)],
            );
          } else if (request.path == '$root/blocks') {
            data = page(blocked ? [block] : []);
          } else if (request.path.startsWith('$root/blocks/') &&
              request.method == 'DELETE') {
            blocked = false;
          } else if (request.path.endsWith('/block-author')) {
            blocked = true;
            data = block;
          } else if (request.path.endsWith('/reports')) {
            data = {'id': id(8), 'status': 'received'};
          } else if (request.method == 'DELETE') {
            if (stale) {
              fail(409);
              return;
            }
            submitted.clear();
          } else {
            data =
                submitted.values
                    .where((p) => request.path.endsWith(p['id'] as String))
                    .firstOrNull ??
                post(2);
            if (badVersion) data = {...data as Map, 'version': 0};
          }
          handler.resolve(
            Response(
              requestOptions: request,
              statusCode: request.method == 'DELETE' ? 204 : 200,
              data: request.method == 'DELETE'
                  ? null
                  : {'data': data, 'meta': {}},
            ),
          );
        },
      ),
    );
  }
  late ApiClient client;
  late Account account;
  late CommunityApi api;
  final storage = _Storage();
  final requests = <RequestOptions>[];
  final submitted = <String, Map<String, dynamic>>{};
  bool loseResponse = false,
      blocked = false,
      denied = false,
      stale = false,
      badVersion = false;
  Completer<void>? paused;
  CommunityApi newApi() => CommunityApi(
    client,
    account,
    storage,
    serverOrigin: 'https://example.test',
  );
  void changeOwner(int n) {
    account.session = ServiceSession(
      userId: id(n),
      token: 'test-session',
      expiresAt: DateTime.utc(2030),
      kakaoLinked: true,
    );
    account.continueOffline();
  }

  Map<String, dynamic> post(
    int n, {
    bool mine = false,
    String title = '오늘의 식사',
    String text = '따뜻한 밥을 먹었어요.',
  }) => {
    'id': id(n),
    'category': 'meal',
    'title': title,
    'body': text,
    'author_label': '이웃 2',
    'is_mine': mine,
    'status': 'published',
    'version': 2,
    'created_at': '2026-11-25T00:00:00Z',
    'updated_at': '2026-11-25T00:00:00Z',
  };
  Map<String, dynamic> get block => {
    'id': id(9),
    'author_label': '이웃 2',
    'created_at': '2026-11-25T00:00:00Z',
  };
  Map<String, dynamic> page(List<Object?> items) => {
    'items': items,
    'total': items.length,
    'offset': 0,
    'limit': 20,
  };
}

Future<void> show(WidgetTester tester, Widget child, {double scale = 1}) async {
  tester.view.physicalSize = const Size(320, 780);
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
      home: child,
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
  expect(tester.takeException(), isNull);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  WidgetController.hitTestWarningShouldBeFatal = true;
  test(
    'session, filters, delete version and block routes follow the server contract',
    () async {
      final server = _Server();
      final page = await server.api.posts(
        category: CommunityCategory.daily,
        offset: 20,
      );
      expect(page.items.single.title, '오늘의 식사');
      expect(server.requests.single.queryParameters, {
        'limit': 20,
        'offset': 20,
        'category': 'daily',
      });
      expect(
        server.requests.single.headers['Authorization'],
        'Bearer test-session',
      );
      expect(server.requests.single.followRedirects, false);
      final post = await server.api.detail(id(2));
      await server.api.remove(post);
      expect(server.requests.last.data, {'expected_version': 2});
      await server.api.report(post.id, 'privacy');
      expect(server.requests.last.data, {'reason': 'privacy', 'note': ''});
      await server.api.block(post.id);
      expect((await server.api.blocks()).items.single.id, id(9));
      await server.api.unblock(id(9));
      expect((await server.api.blocks()).items, isEmpty);
      server.stale = true;
      await expectLater(
        server.api.remove(post),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 409)),
      );
    },
  );
  test(
    'lost response survives a recreated API and replays exactly one submission',
    () async {
      final server = _Server()..loseResponse = true;
      final pending = await server.api.prepare(
        CommunityCategory.meal,
        '한 끼',
        '맛있게 먹었어요',
      );
      await expectLater(
        server.api.submit(pending),
        throwsA(isA<ApiException>()),
      );
      expect(server.submitted.length, 1);
      final restored = await server.newApi().pending();
      expect(restored!.submissionId, pending.submissionId);
      await server.newApi().submit(restored);
      expect(server.submitted.length, 1);
      expect(await server.api.pending(), isNull);
      final ids = server.requests
          .where((r) => r.method == 'POST')
          .map((r) => r.data['submission_id']);
      expect(ids.toSet(), {pending.submissionId});
    },
  );
  test(
    'pending receipts are isolated by user and a stale response is rejected',
    () async {
      final server = _Server();
      await server.api.prepare(CommunityCategory.meal, '내 제목', '내 이야기');
      server.changeOwner(3);
      expect(await server.api.pending(), isNull);
      server.paused = Completer<void>();
      final future = server.api.posts();
      await Future<void>.delayed(Duration.zero);
      server.changeOwner(4);
      server.paused!.complete();
      await expectLater(future, throwsA(isA<ApiException>()));
    },
  );
  test(
    'failed receipt persistence cannot publish a post; malformed records fail closed',
    () async {
      final server = _Server()..storage.failWrite = true;
      await expectLater(
        server.api.prepare(CommunityCategory.meal, '제목', '내용'),
        throwsA(isA<PlatformException>()),
      );
      expect(server.requests, isEmpty);
      server.badVersion = true;
      await expectLater(server.api.detail(id(2)), throwsA(isA<ApiException>()));
      await expectLater(
        server.api.detail('../../outside'),
        throwsA(isA<FormatException>()),
      );
      expect(server.requests.length, 1);
    },
  );
  for (final scale in [1.0, 1.4]) {
    testWidgets(
      'write, confirm public posting, inspect and delete at scale $scale',
      (tester) async {
        final server = _Server();
        await show(
          tester,
          CommunityScreen(api: server.api, settings: AppSettings()),
          scale: scale,
        );
        await tap(tester, find.byKey(const Key('community-write')));
        await tester.enterText(
          find.byKey(const Key('community-title')),
          '나의 한 끼',
        );
        await tester.enterText(
          find.byKey(const Key('community-body')),
          '따뜻한 죽을 먹었어요.',
        );
        await tap(tester, find.byType(CheckboxListTile));
        await tap(tester, find.byKey(const Key('community-send')));
        expect(server.submitted, isEmpty);
        await tap(tester, find.text('공개하기'));
        expect(server.submitted.length, 1);
        expect(find.text('나의 한 끼'), findsOneWidget);
        await tap(tester, find.text('내 글 삭제'));
        expect(server.submitted.length, 1);
        await tap(tester, find.text('삭제하기'));
        expect(server.submitted, isEmpty);
      },
    );
  }
  testWidgets('report, block and unblock use visible author actions', (
    tester,
  ) async {
    final server = _Server();
    await show(
      tester,
      CommunityScreen(api: server.api, settings: AppSettings()),
    );
    await tap(tester, find.text('오늘의 식사'));
    await tap(tester, find.text('문제 있는 글 신고'));
    await tap(tester, find.text('개인정보 노출'));
    expect(server.requests.last.data, {'reason': 'privacy', 'note': ''});
    await tap(tester, find.text('이 작성자 차단'));
    await tap(tester, find.text('차단하기'));
    expect(find.text('오늘의 식사'), findsNothing);
    await tap(tester, find.text('차단 관리'));
    await tap(tester, find.text('차단 해제'));
    await tap(tester, find.text('해제하기'));
    expect(server.blocked, false);
    expect(find.text('차단한 사람이 없어요.'), findsOneWidget);
  });
  testWidgets('draft disappears immediately when identity changes', (
    tester,
  ) async {
    final server = _Server();
    await show(
      tester,
      CommunityScreen(api: server.api, settings: AppSettings()),
    );
    await tap(tester, find.byKey(const Key('community-write')));
    await tester.enterText(find.byKey(const Key('community-body')), '개인적인 내용');
    server.changeOwner(3);
    await tester.pumpAndSettle();
    expect(find.text('개인적인 내용'), findsNothing);
    expect(find.text('계정을 확인한 뒤 커뮤니티를 다시 열어 주세요.'), findsOneWidget);
    expect(server.submitted, isEmpty);
  });
  testWidgets('playground exposes the community alongside games and videos', (
    tester,
  ) async {
    final server = _Server();
    await show(
      tester,
      Scaffold(
        body: ContentScreen(settings: AppSettings(), communityApi: server.api),
      ),
      scale: 1.4,
    );
    await tap(tester, find.byKey(const Key('playground-community')));
    expect(find.byKey(const Key('community-write')), findsOneWidget);
    expect(find.text('오늘의 식사'), findsOneWidget);
  });
}
