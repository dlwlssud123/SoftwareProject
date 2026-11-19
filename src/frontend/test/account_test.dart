import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/app.dart';
import 'package:valueflow/core/network/api_client.dart';
import 'package:valueflow/core/network/api_exception.dart';
import 'package:valueflow/data/auth_api.dart';
import 'package:valueflow/data/demo_repository.dart';
import 'package:valueflow/data/profile_api.dart';
import 'package:valueflow/services/account.dart';
import 'package:valueflow/services/settings.dart';
import 'package:valueflow/data/guest_session.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const storage = FlutterSecureStorage();
  const serverUrl = 'https://example.test';
  const storageKey = 'service-session:$serverUrl';
  final token = List.filled(43, 'a').join();
  var guestCount = 0;
  var linked = false;
  var conflict = false;
  var revoked = false;
  Map<String, dynamic>? preferences;
  final updates = <Map<String, dynamic>>[];

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    guestCount = 0;
    linked = false;
    conflict = false;
    revoked = false;
    preferences = null;
    updates.clear();
  });

  Account account() {
    final dio = Dio(BaseOptions(baseUrl: serverUrl));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final path = options.path;
          final isGuest = path.endsWith('/guest');
          final isLink = path.endsWith('/kakao/link');
          final isLogin = path.endsWith('/kakao');
          final isLogout = path.endsWith('/session');
          if (isGuest) {
            guestCount++;
          } else if (!isLogin) {
            expect(options.headers['Authorization'], 'Bearer $token');
            expect(options.followRedirects, isFalse);
          }
          if (path == '/api/v1/profile') {
            if (options.method == 'PATCH') {
              final update = Map<String, dynamic>.from(options.data as Map);
              updates.add(update);
              preferences = update['consent'] == false
                  ? null
                  : {
                      ...?preferences,
                      ...Map<String, dynamic>.from(
                        update['preferences'] as Map,
                      ),
                    };
            } else {
              expect(options.method, 'GET');
            }
            handler.resolve(
              Response(
                requestOptions: options,
                data: {
                  'data': preferences == null
                      ? null
                      : {'preferences': preferences},
                },
              ),
            );
            return;
          }
          if (isLink) {
            expect(options.data, {'access_token': 'synthetic-kakao-token'});
            if (conflict) {
              handler.reject(
                DioException.badResponse(
                  statusCode: 409,
                  requestOptions: options,
                  response: Response(
                    requestOptions: options,
                    statusCode: 409,
                    data: {
                      'error': {'message': '이미 연결된 계정이에요.'},
                    },
                  ),
                ),
                true,
              );
              return;
            }
            linked = true;
          }
          if (isLogout) revoked = true;
          if (isLogin) linked = true;
          handler.resolve(
            Response(
              requestOptions: options,
              data: {
                'data': {
                  'user_id': isLogin ? 'account-2' : 'guest-1',
                  if (isGuest || isLogin) 'access_token': token,
                  'expires_at': DateTime.now()
                      .add(const Duration(days: 3))
                      .toIso8601String(),
                  'kakao_linked': linked,
                },
              },
            ),
          );
        },
      ),
    );
    final client = ApiClient(dio: dio);
    return Account(
      AuthApi(client),
      storage,
      profiles: ProfileApi(client),
      serverUrl: serverUrl,
      kakaoEnabled: true,
      getKakaoToken: () async => 'synthetic-kakao-token',
    );
  }

  test('앱 재시작과 카카오 연결 후 게스트 사용자 ID를 유지한다', () async {
    final first = account();
    await first.startGuest();
    expect(await storage.read(key: storageKey), token);
    final restarted = account();
    await restarted.restore();
    expect(restarted.entered, isTrue);
    expect(restarted.session!.userId, first.session!.userId);
    expect(guestCount, 1);

    conflict = true;
    await restarted.connectKakao();
    expect(restarted.message, '이미 연결된 계정이에요.');
    expect(restarted.session!.kakaoLinked, isFalse);
    expect(await storage.read(key: storageKey), token);
    conflict = false;
    await restarted.connectKakao();
    expect(restarted.session!.userId, first.session!.userId);
    expect(restarted.session!.kakaoLinked, isTrue);
  });

  test('만료된 개인 API 세션을 새 게스트로 바꾸지 않고 재로그인을 안내한다', () async {
    final auth = account();
    await auth.startGuest();
    await expectLater(
      auth.request<void>((_) async {
        throw const ApiException(
          ApiErrorType.badResponse,
          '만료된 세션',
          statusCode: 401,
        );
      }),
      throwsA(isA<ApiException>()),
    );
    expect(auth.session, isNull);
    expect(auth.entered, isFalse);
    expect(guestCount, 1);
    expect(await storage.read(key: storageKey), isNull);
    expect(auth.message, contains('다시 로그인'));
  });

  test('기존 식단 세션을 새 계정 저장소로 옮기고 같은 토큰으로 요청한다', () async {
    await storage.write(key: 'mealGuest:$serverUrl', value: token);
    final auth = account();
    await auth.restore();
    expect(auth.entered, isTrue);
    expect(guestCount, 0);
    expect(await storage.read(key: storageKey), token);
    expect(await storage.read(key: 'mealGuest:$serverUrl'), isNull);
    final bridge = GuestSession(ApiClient(), account: auth);
    expect(await bridge.request((value) async => value), token);
    await auth.connectKakao();
    expect(await bridge.request((value) async => value), token);
    expect(auth.session!.kakaoLinked, isTrue);
    expect(guestCount, 0);
  });

  test('만료된 계정 세션이 있어도 유효한 기존 식단 세션을 복구한다', () async {
    final expired = List.filled(43, 'z').join();
    await storage.write(key: storageKey, value: expired);
    await storage.write(key: 'mealGuest:$serverUrl', value: token);
    final dio = Dio(BaseOptions(baseUrl: serverUrl));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          if (options.headers['Authorization'] == 'Bearer $expired') {
            handler.reject(
              DioException.badResponse(
                statusCode: 401,
                requestOptions: options,
                response: Response(requestOptions: options, statusCode: 401),
              ),
            );
          } else {
            expect(options.headers['Authorization'], 'Bearer $token');
            handler.resolve(
              Response(
                requestOptions: options,
                data: {
                  'data': {
                    'user_id': 'meal-user',
                    'expires_at': DateTime.now()
                        .add(const Duration(days: 3))
                        .toIso8601String(),
                    'kakao_linked': false,
                  },
                },
              ),
            );
          }
        },
      ),
    );
    final client = ApiClient(dio: dio);
    final auth = Account(
      AuthApi(client),
      storage,
      profiles: ProfileApi(client),
      serverUrl: serverUrl,
      kakaoEnabled: true,
    );
    await auth.restore();
    expect(auth.session!.userId, 'meal-user');
    expect(await storage.read(key: storageKey), token);
  });

  testWidgets('설정에서 로그아웃하면 시작 화면으로 돌아온다', (tester) async {
    final session = account();
    await tester.runAsync(() async {
      await session.startGuest();
      await session.connectKakao();
    });
    await tester.pumpWidget(
      ValueFlowApp(
        repository: const DemoRepository([], []),
        settings: AppSettings(),
        account: session,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('로그아웃'));
    await tester.pumpAndSettle();
    expect(revoked, isTrue);
    expect(await storage.read(key: storageKey), isNull);
    expect(find.text('게스트로 시작하기'), findsOneWidget);
    expect(find.text('카카오 로그인'), findsOneWidget);
  });

  testWidgets('연결 충돌 후 동의해야 기존 계정으로 전환하고 이전 화면을 닫는다', (tester) async {
    final auth = account();
    await tester.runAsync(auth.startGuest);
    conflict = true;
    await tester.pumpWidget(
      ValueFlowApp(
        repository: const DemoRepository([], []),
        settings: AppSettings(),
        account: auth,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('settings-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('카카오 로그인'));
    await tester.pumpAndSettle();
    expect(auth.session!.userId, 'guest-1');
    await tester.ensureVisible(find.text('기존 계정으로 로그인'));
    await tester.tap(find.text('기존 계정으로 로그인'));
    await tester.pumpAndSettle();
    expect(auth.session!.userId, 'guest-1');
    await tester.tap(find.text('로그인'));
    await tester.pumpAndSettle();
    expect(auth.session!.userId, 'account-2');
    expect(find.text('설정'), findsNothing);
    expect(find.byKey(const Key('settings-button')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('게스트 프로필은 동의 후 저장하고 다시 열어 수정하고 철회한다', (tester) async {
    final session = account();
    await tester.runAsync(() => session.startGuest());
    await tester.pumpWidget(
      ValueFlowApp(
        repository: const DemoRepository([], []),
        settings: AppSettings(),
        account: session,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('settings-button')));
    await tester.pumpAndSettle();
    final manage = find.text('저장할 추천 조건 관리');
    await tester.tap(manage);
    await tester.pumpAndSettle();

    Future<void> tapOnForm(String text) async {
      final target = find.text(text);
      await tester.dragUntilVisible(
        target,
        find.byType(SingleChildScrollView).first,
        const Offset(0, -300),
      );
      await tester.ensureVisible(target);
      await tester.tap(target);
      await tester.pumpAndSettle();
    }

    Finder field(String label) => find.widgetWithText(TextFormField, label);
    await tester.enterText(field('나이 (선택)'), '72');
    await tapOnForm('달걀');
    await tapOnForm('추천 조건 저장');
    expect(updates, isEmpty);
    expect(find.text('서버 저장에 동의해 주세요.'), findsOneWidget);

    await tapOnForm('추천 조건을 서버에 저장하는 데 동의해요.');
    await tapOnForm('추천 조건 저장');
    expect(updates.single['consent'], isTrue);
    expect(preferences!['age'], 72);
    expect(preferences!['exclude_allergens'], ['알류']);

    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    await tester.tap(manage);
    await tester.pumpAndSettle();
    expect(find.text('72'), findsOneWidget);
    await tester.enterText(field('나이 (선택)'), '73');
    await tapOnForm('추천 조건 저장');
    expect(updates.last, {
      'preferences': {'age': 73},
    });
    expect(preferences!['age'], 73);

    await tapOnForm('저장 동의 철회');
    await tester.tap(find.text('철회하고 삭제'));
    await tester.pumpAndSettle();
    expect(updates.last, {'consent': false});
    expect(preferences, isNull);
    expect(find.text('저장 동의 철회'), findsNothing);
  });
}
