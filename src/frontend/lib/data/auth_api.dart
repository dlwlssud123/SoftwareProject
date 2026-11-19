import '../core/network/api_client.dart';

class ServiceSession {
  const ServiceSession({
    required this.userId,
    required this.token,
    required this.expiresAt,
    required this.kakaoLinked,
  });

  final String userId;
  final String token;
  final DateTime expiresAt;
  final bool kakaoLinked;
}

class AuthApi {
  const AuthApi(this._client);
  final ApiClient _client;

  Future<ServiceSession> guest() => _client.post(
    '/api/v1/auth/guest',
    body: <String, Object>{},
    followRedirects: false,
    parse: _session,
  );

  Future<ServiceSession> current(String token) => _client.get(
    '/api/v1/auth/me',
    token: token,
    parse: (body) => _session(body, token),
  );

  Future<ServiceSession> refresh(String token) =>
      _client.post('/api/v1/auth/refresh', token: token, parse: _session);

  Future<ServiceSession> kakao(String kakaoToken, {String? serviceToken}) =>
      _client.post(
        serviceToken == null ? '/api/v1/auth/kakao' : '/api/v1/auth/kakao/link',
        token: serviceToken,
        body: {'access_token': kakaoToken},
        followRedirects: false,
        parse: (body) => _session(body, serviceToken),
      );

  Future<void> revoke(String token) =>
      _client.delete('/api/v1/auth/session', token: token);

  static ServiceSession _session(Object? body, [String? currentToken]) {
    final data = body is Map<String, dynamic> ? body['data'] : null;
    if (data is! Map<String, dynamic>) {
      throw const FormatException('Session data is missing');
    }
    final userId = data['user_id'];
    final token = currentToken ?? data['access_token'];
    final expires = data['expires_at'];
    final linked = data['kakao_linked'];
    if (userId is! String ||
        userId.isEmpty ||
        token is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(token) ||
        expires is! String ||
        (linked != null && linked is! bool)) {
      throw const FormatException('Invalid session data');
    }
    return ServiceSession(
      userId: userId,
      token: token,
      expiresAt: DateTime.parse(expires),
      kakaoLinked: linked == true,
    );
  }
}
