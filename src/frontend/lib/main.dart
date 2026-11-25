import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:kakao_flutter_sdk_user/kakao_flutter_sdk_user.dart'
    show KakaoSdk;
import 'app.dart';
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
  runApp(
    ValueFlowApp(
      repository: repository,
      settings: settings,
      recipeApi: recipeApi,
      account: account,
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
