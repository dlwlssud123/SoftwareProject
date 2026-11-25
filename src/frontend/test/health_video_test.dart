import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/health_video_api.dart';
import 'package:valueflow/models/health_video.dart';
import 'package:valueflow/screens/content_screen.dart';
import 'package:valueflow/screens/health_video_screens.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/theme.dart';

const source =
    'https://www.seohae.go.kr/open_content/office/bbs/bbsMsgDetail.do?bcd=notice&msg_seq=25922';
Map<String, dynamic> video() => {
  'id': 'chair-stretching',
  'topic': 'stretching',
  'title': '의자에 앉아 스트레칭',
  'publisher': '인천광역시서구체육회',
  'video_id': 'REfwqrdhab4',
  'source_url': source,
  'checked_on': '2026-11-25',
};

class _Server {
  _Server() {
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    api = HealthVideoApi(ApiClient(dio: dio));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          requests.add(options);
          final detail = options.path.endsWith('/chair-stretching');
          final status = fail
              ? 503
              : removed && detail
              ? 404
              : 200;
          if (status != 200) {
            handler.reject(
              DioException(
                requestOptions: options,
                type: DioExceptionType.badResponse,
                response: Response(
                  requestOptions: options,
                  statusCode: status,
                  data: {
                    'error': {
                      'message': status == 404
                          ? '지금은 제공하지 않는 영상이에요.'
                          : '목록을 불러오지 못했어요.',
                      'retryable': status == 503,
                    },
                  },
                ),
              ),
            );
            return;
          }
          final row = video();
          if (badLink) {
            row['source_url'] = 'https://www.youtube.com.example.test';
          }
          if (wrongId) row['id'] = 'other-video';
          handler.resolve(
            Response(
              requestOptions: options,
              statusCode: 200,
              data: {
                'data': detail
                    ? row
                    : {
                        'items': empty ? [] : [row],
                        'total': empty ? 0 : 1,
                        'offset': 0,
                        'limit': 20,
                      },
                'meta': {},
              },
            ),
          );
        },
      ),
    );
  }
  late HealthVideoApi api;
  final requests = <RequestOptions>[];
  bool fail = false,
      removed = false,
      empty = false,
      badLink = false,
      wrongId = false;
}

Future<void> launch(WidgetTester tester, Widget home) async {
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
        ).copyWith(textScaler: const TextScaler.linear(1.4)),
        child: child!,
      ),
      home: home,
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> tap(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isEmpty) await tester.scrollUntilVisible(finder, 150);
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
    'filters, checked source, public requests and exact watch URL are parsed',
    () async {
      final server = _Server();
      final page = await server.api.list(
        topic: VideoTopic.stretching,
        offset: 20,
      );
      expect(server.requests.single.queryParameters, {
        'limit': 20,
        'offset': 20,
        'topic': 'stretching',
      });
      expect(server.requests.single.headers['Authorization'], isNull);
      final item = await server.api.detail(page.items.single.id);
      expect(
        item.watchUrl.toString(),
        'https://www.youtube.com/watch?v=REfwqrdhab4',
      );
      expect(item.sourceUrl.toString(), source);
      expect(item.checkedOn, '2026-11-25');
      await expectLater(
        () => server.api.detail('../wrong'),
        throwsFormatException,
      );
      expect(server.requests.length, 2);
      server.badLink = true;
      await expectLater(server.api.list(), throwsA(isA<ApiException>()));
      server.badLink = false;
      server.wrongId = true;
      await expectLater(
        server.api.detail('chair-stretching'),
        throwsA(isA<ApiException>()),
      );
    },
  );
  test('broken watch identifiers and impossible review dates fail closed', () {
    for (final changes in [
      {'video_id': '../outside'},
      {'checked_on': '2026-02-31'},
      {'source_url': 'http://www.youtube.com/watch'},
    ]) {
      expect(
        () => HealthVideo.fromJson({...video(), ...changes}),
        throwsFormatException,
      );
    }
  });
  testWidgets(
    'official list opens detail and playback only occurs after the button',
    (tester) async {
      final server = _Server();
      const channel = MethodChannel('plugins.flutter.io/url_launcher');
      final links = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
        call,
      ) async {
        links.add((call.arguments as Map)['url'] as String);
        return true;
      });
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          channel,
          null,
        ),
      );
      await launch(
        tester,
        Scaffold(
          body: ContentScreen(
            settings: AppSettings(),
            healthVideoApi: server.api,
          ),
        ),
      );
      await tap(tester, find.byKey(const Key('playground-videos')));
      await tap(tester, find.byKey(const Key('health-video-chair-stretching')));
      expect(find.text('게시 기관: 인천광역시서구체육회'), findsOneWidget);
      expect(links, isEmpty);
      await tap(tester, find.byKey(const Key('health-video-play')));
      expect(links, ['https://www.youtube.com/watch?v=REfwqrdhab4']);
      await tap(tester, find.text('기관 출처 보기'));
      expect(links.last, source);
    },
  );
  testWidgets(
    'stale published list rechecks removal before enabling playback',
    (tester) async {
      final server = _Server();
      await launch(
        tester,
        Scaffold(
          body: HealthVideoCatalog(api: server.api, settings: AppSettings()),
        ),
      );
      server.removed = true;
      await tap(tester, find.byKey(const Key('health-video-chair-stretching')));
      expect(find.text('지금은 제공하지 않는 영상이에요.'), findsOneWidget);
      expect(find.byKey(const Key('health-video-play')), findsNothing);
    },
  );
  testWidgets(
    'loading failures can retry and empty topics are distinct from errors',
    (tester) async {
      final server = _Server()..fail = true;
      await launch(
        tester,
        Scaffold(
          body: SingleChildScrollView(
            child: HealthVideoCatalog(api: server.api, settings: AppSettings()),
          ),
        ),
      );
      expect(find.text('목록을 불러오지 못했어요.'), findsOneWidget);
      server.fail = false;
      server.empty = true;
      await tap(tester, find.text('건강 영상 다시 불러오기'));
      expect(find.text('이 주제에 등록된 영상이 아직 없어요. 다른 주제를 골라 주세요.'), findsOneWidget);
      expect(find.text('목록을 불러오지 못했어요.'), findsNothing);
    },
  );
  testWidgets('failed YouTube launch gives actionable feedback', (
    tester,
  ) async {
    final server = _Server();
    const channel = MethodChannel('plugins.flutter.io/url_launcher');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      channel,
      (_) async => false,
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        null,
      ),
    );
    await launch(
      tester,
      HealthVideoDetail(
        api: server.api,
        id: 'chair-stretching',
        settings: AppSettings(),
      ),
    );
    await tap(tester, find.byKey(const Key('health-video-play')));
    expect(find.text('연결할 수 없어요. 인터넷 연결과 브라우저를 확인해 주세요.'), findsOneWidget);
  });
}
