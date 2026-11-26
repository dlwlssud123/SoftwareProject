import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:kakao_flutter_sdk_user/kakao_flutter_sdk_user.dart'
    show KakaoSdk;
import 'app.dart';
import 'services/usage_recorder.dart';
import 'core/network/api_client.dart';
import 'core/network/api_config.dart';
import 'data/recipe_api.dart';
import 'data/demo_repository.dart';
import 'services/settings.dart';
import 'services/account.dart';
import 'data/auth_api.dart';
import 'data/profile_api.dart';
import 'data/intake_api.dart';
import 'data/welfare_api.dart';
import 'data/topic_api.dart';
import 'data/facility_api.dart';
import 'data/ai_api.dart';
import 'data/community_api.dart';
import 'data/health_video_api.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.dark,
      systemNavigationBarColor: Colors.white,
      systemNavigationBarIconBrightness: Brightness.dark,
    ),
  );
  final repository = await DemoRepository.load();
  final settings = await AppSettings.load();
  // 서버 주소(--dart-define=API_BASE_URL)가 있을 때만 서버 레시피를 연결한다.
  final recipeApi = ApiConfig.hasServer ? RecipeApi(ApiClient()) : null;
  final server = Uri.tryParse(ApiConfig.baseUrl);
  Account? account;
  if (server != null &&
      server.host.isNotEmpty &&
      server.userInfo.isEmpty &&
      (server.scheme == 'https' ||
          (kDebugMode &&
              server.scheme == 'http' &&
              const {
                '10.0.2.2',
                '127.0.0.1',
                'localhost',
              }.contains(server.host)))) {
    const nativeKey = String.fromEnvironment('KAKAO_NATIVE_APP_KEY');
    var kakaoEnabled = false;
    if (nativeKey.isNotEmpty &&
        !kIsWeb &&
        defaultTargetPlatform == TargetPlatform.android) {
      try {
        await KakaoSdk.init(nativeAppKey: nativeKey);
        kakaoEnabled = true;
      } on Exception {
        // Guest access remains available when the native SDK cannot initialize.
      }
    }
    final client = ApiClient();
    account = Account(
      AuthApi(client),
      const FlutterSecureStorage(),
      profiles: ProfileApi(client),
      serverUrl: server.origin,
      kakaoEnabled: kakaoEnabled,
    );
    account.restore();
  }
  if (account != null) {
    final telemetryClient = ApiClient();
    final usage = UsageRecorder(
      enabled: () => settings.usageSharing,
      token: () => account?.session?.token,
      platform: kIsWeb
          ? 'web'
          : defaultTargetPlatform == TargetPlatform.android
          ? 'android'
          : defaultTargetPlatform == TargetPlatform.iOS
          ? 'ios'
          : 'desktop',
      send: (events, token) => telemetryClient.post<void>(
        '/api/v1/usage-events',
        token: token,
        body: {'consent_version': 'usage-v1', 'events': events},
        receiveTimeout: const Duration(seconds: 5),
        parse: (_) {},
      ),
    );
    UsageRecorder.current = usage;
    final previousFlutterError = FlutterError.onError;
    FlutterError.onError = (details) {
      usage.record(
        'app_error',
        'app',
        outcome: 'failure',
        errorKind: 'unknown',
      );
      if (previousFlutterError != null) {
        previousFlutterError(details);
      } else {
        FlutterError.presentError(details);
      }
    };
    final previousPlatformError = PlatformDispatcher.instance.onError;
    PlatformDispatcher.instance.onError = (error, stack) {
      usage.record(
        'app_error',
        'app',
        outcome: 'failure',
        errorKind: 'unknown',
      );
      return previousPlatformError?.call(error, stack) ?? false;
    };
    settings.addListener(usage.changed);
    account.addListener(usage.changed);
  }
  runApp(
    ValueFlowApp(
      repository: repository,
      settings: settings,
      recipeApi: recipeApi,
      account: account,
      communityApi: account == null
          ? null
          : CommunityApi(
              ApiClient(),
              account,
              const FlutterSecureStorage(),
              serverOrigin: server!.origin,
            ),
      healthVideoApi: ApiConfig.hasServer ? HealthVideoApi(ApiClient()) : null,
      aiApi: account == null ? null : AiApi(ApiClient(), account),
      facilityApi: account == null ? null : FacilityApi(ApiClient()),
      welfareApi: account == null ? null : WelfareApi(ApiClient(), account),
      topicApi: account == null
          ? null
          : TopicApi(
              ApiClient(),
              account,
              const FlutterSecureStorage(),
              serverOrigin: server!.origin,
            ),
      intakeApi: account == null
          ? null
          : IntakeApi(
              ApiClient(),
              account,
              const FlutterSecureStorage(),
              serverOrigin: server!.origin,
            ),
    ),
  );
}
