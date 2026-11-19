import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../core/network/api_client.dart';
import '../core/network/api_exception.dart';
import '../services/account.dart';

/// Shares the same server identity across personal recipe and recommendation requests.
class GuestSession {
  GuestSession(this._client, {this.storageKey, this.account});

  final ApiClient _client;
  final String? storageKey;
  final Account? account;
  Future<String>? _token;

  Future<T> request<T>(Future<T> Function(String token) send) async {
    if (account case final auth?) return auth.request(send);
    final pending = _token ??= _loadToken();
    late final String token;
    try {
      token = await pending;
    } on ApiException {
      if (identical(_token, pending)) _token = null;
      rethrow;
    }
    try {
      return await send(token);
    } on ApiException catch (error) {
      if (error.statusCode != 401) rethrow;
      final renewal = identical(_token, pending)
          ? (_token = _loadToken(renew: true))
          : (_token ??= _loadToken(renew: true));
      try {
        return await send(await renewal);
      } on ApiException {
        if (identical(_token, renewal)) _token = null;
        rethrow;
      }
    }
  }

  Future<String> _loadToken({bool renew = false}) async {
    final key = storageKey;
    const storage = FlutterSecureStorage();
    if (key != null && !renew) {
      try {
        final stored = await storage.read(key: key);
        if (stored != null && _validToken(stored)) return stored;
      } on Exception {
        // The current app session can work without device persistence.
      }
    }
    final token = await _client.post(
      '/api/v1/auth/guest',
      body: <String, Object>{},
      followRedirects: false,
      parse: (body) {
        final data = body is Map ? body['data'] : null;
        final token = data is Map ? data['access_token'] : null;
        if (token is! String || !_validToken(token)) {
          throw const FormatException('Invalid service session');
        }
        return token;
      },
    );
    if (key != null) {
      try {
        await storage.write(key: key, value: token);
      } on Exception {
        // Retain the working session in memory.
      }
    }
    return token;
  }

  static bool _validToken(String token) =>
      RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(token);
}
