import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'app.dart';
import 'core/network/api_client.dart';
import 'core/network/api_config.dart';
import 'data/recipe_api.dart';
import 'data/demo_repository.dart';
import 'services/settings.dart';

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
  runApp(
    ValueFlowApp(
      repository: repository,
      settings: settings,
      recipeApi: recipeApi,
    ),
  );
}
