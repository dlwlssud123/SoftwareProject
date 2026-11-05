/// 서버 연결 설정.
///
/// 서버 주소는 코드에 적지 않고 실행할 때 주입한다.
///   flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
/// (안드로이드 에뮬레이터에서 내 PC의 localhost는 10.0.2.2)
class ApiConfig {
  const ApiConfig._();

  static const String baseUrl = String.fromEnvironment('API_BASE_URL');
  static const Duration connectTimeout = Duration(seconds: 10);
  static const Duration receiveTimeout = Duration(seconds: 15);

  /// 서버 주소가 없으면 기존 데모 데이터로 동작한다.
  static bool get hasServer => baseUrl.isNotEmpty;
}
