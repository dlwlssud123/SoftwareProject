import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/facility_api.dart';
import 'package:valueflow/models/facility.dart';
import 'package:valueflow/screens/facility_screens.dart';
import 'package:valueflow/services/facility_location.dart';
import 'package:valueflow/theme.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/services/settings.dart';

const _id = '00000000-0000-4000-8000-000000000001';
Map<String, dynamic> _facility({String id = _id}) => {
  'id': id,
  'name': '남구 경로식당',
  'sido': '대구광역시',
  'sigungu': '남구',
  'address': '대구광역시 남구 중앙대로 1',
  'eligibility_text': '만 65세 이상, 기관 확인',
  'hours_text': '평일 12시',
  'contact_text': '053-123-4567',
  'source_url': 'https://www.data.go.kr/data/facilities',
  'provider': '공공데이터',
  'checked_on': '2026-11-20',
  'reference_date': '2026-10-01',
  'quality_flags': [],
  'cautions': ['방문 전에 전화로 확인해 주세요.'],
};

class _Location extends GeolocatorPlatform {
  bool enabled = true, cancelled = false;
  int permissions = 0, streams = 0;
  LocationPermission permission = LocationPermission.whileInUse;
  Future<LocationPermission>? grant;
  late final controller = StreamController<Position>.broadcast(
    onCancel: () => cancelled = true,
  );
  @override
  Future<bool> isLocationServiceEnabled() async => enabled;
  @override
  Future<LocationPermission> checkPermission() async => permission;
  @override
  Future<LocationPermission> requestPermission() async {
    permissions++;
    return grant ?? permission;
  }

  @override
  Stream<Position> getPositionStream({LocationSettings? locationSettings}) {
    streams++;
    return controller.stream;
  }
}

Position _position({DateTime? timestamp, double accuracy = 40}) => Position(
  longitude: 128.6,
  latitude: 35.87,
  timestamp: timestamp ?? DateTime.now(),
  accuracy: accuracy,
  altitude: 0,
  altitudeAccuracy: 0,
  heading: 0,
  headingAccuracy: 0,
  speed: 0,
  speedAccuracy: 0,
);

class _Backend {
  _Backend() {
    final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    api = FacilityApi(ApiClient(dio: dio));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          requests.add(options);
          if (delay != null) await delay!.future;
          if (fail || (missing && options.path.endsWith(_id))) {
            handler.reject(
              DioException(
                requestOptions: options,
                type: DioExceptionType.badResponse,
                response: Response(
                  requestOptions: options,
                  statusCode: missing ? 404 : 503,
                ),
              ),
            );
            return;
          }
          Object data;
          if (options.path.endsWith(_id)) {
            data = _facility();
          } else {
            final nearby = options.method == 'POST';
            final offset =
                ((nearby ? options.data : options.queryParameters)
                        as Map)['offset']
                    as int;
            data = {
              'items': empty
                  ? []
                  : [
                      {
                        ..._facility(
                          id: offset == 0
                              ? _id
                              : '00000000-0000-4000-8000-000000000002',
                        ),
                        if (nearby) 'distance_km': 0.8,
                      },
                    ],
              'total': empty ? 0 : 2,
              'offset': offset,
              'limit': 20,
              'warnings': nearby ? ['직선거리 기준이에요.'] : [],
            };
          }
          handler.resolve(
            Response(
              requestOptions: options,
              statusCode: 200,
              data: {'data': data},
            ),
          );
        },
      ),
    );
  }
  late final FacilityApi api;
  final requests = <RequestOptions>[];
  bool missing = false, fail = false, empty = false;
  Completer<void>? delay;
}

Future<void> _screen(
  WidgetTester tester,
  _Backend backend, {
  _Location? location,
  double scale = 1,
  Size size = const Size(400, 850),
}) async {
  tester.view.physicalSize = size;
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
      home: FacilitySearchScreen(
        api: backend.api,
        locationFactory: location == null
            ? null
            : () => FacilityLocationLookup(platform: location),
      ),
    ),
  );
  await tester.pump();
}

Future<void> _region(WidgetTester tester) async {
  final region = find.byKey(const Key('facility-region'));
  await tester.scrollUntilVisible(region, 250, scrollable: _listScroll());
  await tester.tap(region);
  await tester.pumpAndSettle();
  await tester.tap(find.text('대구광역시').last);
  await tester.pumpAndSettle();
}

Future<void> _findRegion(WidgetTester tester) async {
  final button = find.byKey(const Key('facility-find-region'));
  await tester.scrollUntilVisible(button, 250, scrollable: _listScroll());
  await tester.tap(button);
  await tester.pumpAndSettle();
}

Finder _listScroll() => find
    .descendant(
      of: find.byType(ListView).first,
      matching: find.byType(Scrollable),
    )
    .first;

void _backgroundAndResume(WidgetTester tester) {
  for (final state in [
    AppLifecycleState.inactive,
    AppLifecycleState.hidden,
    AppLifecycleState.paused,
    AppLifecycleState.hidden,
    AppLifecycleState.inactive,
    AppLifecycleState.resumed,
  ]) {
    tester.binding.handleAppLifecycleStateChanged(state);
  }
}

void main() {
  WidgetController.hitTestWarningShouldBeFatal = true;
  test('location is POST body only, never URL, auth or redirect', () async {
    final backend = _Backend();
    final cancel = CancelToken();
    await backend.api.nearby(
      latitude: 35.87,
      longitude: 128.6,
      radiusKm: 5,
      cancelToken: cancel,
    );
    final request = backend.requests.single;
    expect(request.method, 'POST');
    expect(request.queryParameters, isEmpty);
    expect(request.uri.toString(), isNot(contains('35.87')));
    expect(request.headers.containsKey('Authorization'), isFalse);
    expect(request.followRedirects, isFalse);
    expect(request.cancelToken, same(cancel));
    expect(request.data, {
      'latitude': 35.87,
      'longitude': 128.6,
      'radius_km': 5.0,
      'limit': 20,
      'offset': 0,
    });
  });
  test(
    'detail validates UUID and external actions reject unsafe source and phone',
    () async {
      final backend = _Backend();
      expect(() => backend.api.detail('../admin'), throwsFormatException);
      expect(backend.requests, isEmpty);
      for (final source in [
        'http://www.nam.daegu.kr',
        'https://www.nam.daegu.kr.evil.test',
        'https://www.nam.daegu.kr:8443',
      ]) {
        final item = MealFacility.fromJson({
          ..._facility(),
          'source_url': source,
          'contact_text': '*123#',
        });
        expect(item.officialUrl, isNull);
        expect(item.phoneUrl, isNull);
      }
      final good = MealFacility.fromJson(_facility());
      expect(good.phoneUrl.toString(), 'tel:0531234567');
      expect(good.mapUrl!.host, 'map.naver.com');
      expect(good.officialUrl, isNotNull);
      expect(
        () =>
            MealFacility.fromJson({..._facility(), 'distance_km': double.nan}),
        throwsFormatException,
      );
    },
  );
  test('empty page beyond last offset is valid', () {
    expect(
      FacilityPage.fromJson({
        'items': [],
        'total': 0,
        'offset': 20,
        'warnings': [],
      }).items,
      isEmpty,
    );
  });
  test('invalid envelope becomes actionable API error', () async {
    final dio = Dio()
      ..interceptors.add(
        InterceptorsWrapper(
          onRequest: (o, h) => h.resolve(
            Response(
              requestOptions: o,
              data: {
                'data': {'items': 'broken'},
              },
            ),
          ),
        ),
      );
    await expectLater(
      FacilityApi(ApiClient(dio: dio)).search(region: '대구'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.type,
          'type',
          ApiErrorType.badResponse,
        ),
      ),
    );
  });
  for (final denied in [
    LocationPermission.denied,
    LocationPermission.deniedForever,
  ]) {
    test('permission $denied does not start location stream', () async {
      final platform = _Location()..permission = denied;
      await expectLater(
        FacilityLocationLookup(platform: platform).start(),
        throwsA(isA<FacilityLocationException>()),
      );
      expect(platform.streams, 0);
      expect(platform.permissions, denied == LocationPermission.denied ? 1 : 0);
    });
  }
  test('disabled service avoids permission request', () async {
    final platform = _Location()..enabled = false;
    await expectLater(
      FacilityLocationLookup(platform: platform).start(),
      throwsA(isA<FacilityLocationException>()),
    );
    expect(platform.permissions, 0);
    expect(platform.streams, 0);
  });
  testWidgets(
    'late permission grant after cancellation cannot start tracking',
    (tester) async {
      final grant = Completer<LocationPermission>();
      final platform = _Location()
        ..permission = LocationPermission.denied
        ..grant = grant.future;
      final lookup = FacilityLocationLookup(platform: platform);
      final result = expectLater(
        lookup.start(),
        throwsA(isA<FacilityLocationException>()),
      );
      await tester.pump();
      lookup.cancel();
      grant.complete(LocationPermission.whileInUse);
      await tester.pump();
      await result;
      expect(platform.streams, 0);
    },
  );
  testWidgets('stale fixes wait, valid fix stops stream and timeout cancels', (
    tester,
  ) async {
    final platform = _Location();
    final result = FacilityLocationLookup(platform: platform).start();
    await tester.pump();
    platform.controller.add(
      _position(
        timestamp: DateTime.now().subtract(const Duration(minutes: 10)),
      ),
    );
    await tester.pump();
    expect(platform.cancelled, isFalse);
    platform.controller.add(_position());
    await tester.pump();
    await result;
    expect(platform.cancelled, isTrue);
    final slow = _Location();
    final lookup = FacilityLocationLookup(platform: slow);
    final timeout = expectLater(
      lookup.start(),
      throwsA(isA<FacilityLocationException>()),
    );
    await tester.pump();
    await tester.pump(const Duration(seconds: 16));
    await timeout;
    expect(slow.cancelled, isTrue);
  });
  testWidgets('region search needs no location and opens current detail', (
    tester,
  ) async {
    final backend = _Backend();
    final platform = _Location();
    await _screen(tester, backend, location: platform);
    expect(backend.requests, isEmpty);
    expect(platform.permissions, 0);
    await _findRegion(tester);
    expect(find.text('찾으실 시·도를 선택해 주세요.'), findsOneWidget);
    expect(backend.requests, isEmpty);
    await _region(tester);
    await _findRegion(tester);
    expect(backend.requests.single.queryParameters['region'], '대구광역시');
    final card = find.text('남구 경로식당');
    await tester.ensureVisible(card);
    await tester.tap(card);
    await tester.pumpAndSettle();
    expect(find.text('급식소 상세'), findsOneWidget);
    expect(backend.requests.last.path, '/api/v1/meal-facilities/$_id');
    await tester.ensureVisible(find.text('만 65세 이상, 기관 확인'));
    expect(find.text('만 65세 이상, 기관 확인'), findsOneWidget);
  });
  testWidgets('permission denied still allows manual region search', (
    tester,
  ) async {
    final backend = _Backend(),
        platform = _Location()..permission = LocationPermission.deniedForever;
    await _screen(tester, backend, location: platform);
    await tester.tap(find.byKey(const Key('facility-nearby')));
    await tester.pumpAndSettle();
    expect(backend.requests, isEmpty);
    expect(platform.streams, 0);
    await _region(tester);
    await _findRegion(tester);
    expect(backend.requests.single.method, 'GET');
  });
  testWidgets(
    'nearby paging uses same ephemeral position without asking again',
    (tester) async {
      final backend = _Backend(), platform = _Location();
      await _screen(tester, backend, location: platform);
      await tester.tap(find.byKey(const Key('facility-nearby')));
      await tester.pump();
      platform.controller.add(_position());
      await tester.pumpAndSettle();
      expect(backend.requests.single.method, 'POST');
      final more = find.text('급식소 더 보기');
      await tester.scrollUntilVisible(more, 250, scrollable: _listScroll());
      await tester.pumpAndSettle();
      await tester.ensureVisible(more);
      await tester.pumpAndSettle();
      await tester.tap(more);
      await tester.pumpAndSettle();
      expect(backend.requests.last.data['offset'], 1);
      expect(platform.streams, 1);
      expect(platform.cancelled, isTrue);
    },
  );
  testWidgets('leaving page before permission reply sends no position', (
    tester,
  ) async {
    final backend = _Backend(),
        platform = _Location()..permission = LocationPermission.denied;
    final grant = Completer<LocationPermission>();
    platform.grant = grant.future;
    await _screen(tester, backend, location: platform);
    await tester.tap(find.byKey(const Key('facility-nearby')));
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    grant.complete(LocationPermission.whileInUse);
    await tester.pumpAndSettle();
    expect(platform.streams, 0);
    expect(backend.requests, isEmpty);
    expect(tester.takeException(), isNull);
  });
  testWidgets('404 detail removes actionable content', (tester) async {
    final backend = _Backend()..missing = true;
    await tester.pumpWidget(
      MaterialApp(
        home: FacilityDetailScreen(api: backend.api, id: _id),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('현재 공개된 안내'), findsOneWidget);
    expect(find.text('전화 앱에서 문의하기'), findsNothing);
  });

  testWidgets('native permission overlay does not cancel; background does', (
    tester,
  ) async {
    final backend = _Backend(), platform = _Location();
    await _screen(tester, backend, location: platform);
    await tester.tap(find.byKey(const Key('facility-nearby')));
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    platform.controller.add(_position());
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(backend.requests.length, 1);
    await tester.scrollUntilVisible(
      find.text('찾은 급식소 2곳'),
      250,
      scrollable: _listScroll(),
    );
    _backgroundAndResume(tester);
    await tester.pumpAndSettle();
    expect(find.text('찾은 급식소 2곳'), findsNothing);
  });

  testWidgets(
    'background during location and leaving during HTTP cancel work',
    (tester) async {
      final backend = _Backend(), platform = _Location();
      await _screen(tester, backend, location: platform);
      await tester.tap(find.byKey(const Key('facility-nearby')));
      await tester.pump();
      _backgroundAndResume(tester);
      platform.controller.add(_position());
      await tester.pumpAndSettle();
      expect(platform.cancelled, isTrue);
      expect(backend.requests, isEmpty);
      backend.delay = Completer<void>();
      await _region(tester);
      final button = find.byKey(const Key('facility-find-region'));
      await tester.scrollUntilVisible(button, 250, scrollable: _listScroll());
      await tester.pumpAndSettle();
      await tester.tap(button);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      final request = backend.requests.single;
      await tester.pumpWidget(const SizedBox());
      expect(request.cancelToken!.isCancelled, isTrue);
      backend.delay!.complete();
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('AI assistant entry connects the supplied facility API', (
    tester,
  ) async {
    final backend = _Backend();
    final repository = await tester.runAsync(DemoRepository.load);
    await tester.pumpWidget(
      ValueFlowApp(
        repository: repository!,
        settings: AppSettings(),
        facilityApi: backend.api,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('tab-2')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('무료급식소 · 경로식당'),
      200,
      scrollable: find
          .descendant(
            of: find.byType(ListView).last,
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('무료급식소 · 경로식당'));
    await tester.pumpAndSettle();
    expect(find.byType(FacilitySearchScreen), findsOneWidget);
    await _region(tester);
    await _findRegion(tester);
    expect(backend.requests.single.path, '/api/v1/meal-facilities');
    await tester.tap(find.byKey(const Key('tab-0')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('tab-2')));
    await tester.pumpAndSettle();
    expect(find.text('찾은 급식소 2곳'), findsNothing);
  });
  testWidgets('server failure is explicit and retry does not use demo data', (
    tester,
  ) async {
    final backend = _Backend()..fail = true;
    await _screen(tester, backend);
    await _region(tester);
    await _findRegion(tester);
    expect(find.textContaining('서버에 문제가'), findsOneWidget);
    expect(find.text('남구 경로식당'), findsNothing);
    backend
      ..fail = false
      ..empty = true;
    await _findRegion(tester);
    expect(find.textContaining('등록된 급식소를 찾지 못했어요'), findsOneWidget);
  });
  testWidgets('320px with 180 percent text has usable search and detail', (
    tester,
  ) async {
    final backend = _Backend();
    await _screen(tester, backend, scale: 1.8, size: const Size(320, 900));
    await _region(tester);
    await _findRegion(tester);
    final card = find.text('남구 경로식당');
    await tester.scrollUntilVisible(card, 250, scrollable: _listScroll());
    await tester.pumpAndSettle();
    await tester.ensureVisible(card);
    await tester.pumpAndSettle();
    await tester.tap(card);
    await tester.pumpAndSettle();
    await tester.drag(find.byType(ListView).last, const Offset(0, -1800));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
