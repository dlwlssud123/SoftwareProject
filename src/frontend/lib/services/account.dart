import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:kakao_flutter_sdk_user/kakao_flutter_sdk_user.dart'
    show
        ClientErrorCause,
        KakaoClientException,
        TokenManagerProvider,
        UserApi,
        isKakaoTalkInstalled;

import '../core/network/api_exception.dart';
import '../data/auth_api.dart';
import '../data/profile_api.dart';

class Account extends ChangeNotifier {
  Account(
    this._api,
    this._storage, {
    required this.profiles,
    required String serverUrl,
    required this.kakaoEnabled,
    Future<String?> Function()? getKakaoToken,
  }) : _storageKey = 'service-session:$serverUrl',
       _legacyStorageKey = 'mealGuest:$serverUrl',
       _getKakaoToken = getKakaoToken ?? _loginWithKakao;

  final AuthApi _api;
  final ProfileApi profiles;
  final FlutterSecureStorage _storage;
  final String _storageKey;
  final String _legacyStorageKey;
  final Future<String?> Function() _getKakaoToken;
  final bool kakaoEnabled;
  bool _sessionNeedsSaving = false;
  Future<void>? _requestSession;

  ServiceSession? session;
  bool entered = false;
  bool busy = false;
  bool linkConflict = false;
  String? message;

  Future<void> restore() => _run(() async {
    if (await _restoreSavedSession() != null) entered = true;
  });

  /// Personal resources always use the same identity as the account screen.
  Future<T> request<T>(Future<T> Function(String token) send) async {
    if (session == null) {
      final pending = _requestSession ??= startGuest();
      try {
        await pending;
      } finally {
        if (identical(_requestSession, pending)) _requestSession = null;
      }
    }
    final current = session;
    if (current == null) {
      throw ApiException(
        ApiErrorType.server,
        message ?? '계정을 확인할 수 없어요. 다시 시도해 주세요.',
      );
    }
    try {
      return await send(current.token);
    } on ApiException catch (error) {
      if (error.statusCode == 401 && identical(session, current)) {
        session = null;
        entered = false;
        message = '이용 시간이 만료됐어요. 다시 로그인해 주세요.';
        try {
          await _storage.delete(key: _storageKey);
          await _storage.delete(key: _legacyStorageKey);
        } on PlatformException {
          message = '기기의 만료된 로그인 정보를 정리하지 못했어요. 다시 로그인해 주세요.';
        }
        notifyListeners();
      }
      rethrow;
    }
  }

  Future<void> startGuest() => _run(() async {
    if (await _restoreSavedSession() == null) await _save(await _api.guest());
    entered = true;
  });

  Future<void> connectKakao() => _run(() async {
    final current = await _restoreSavedSession();
    if (current?.kakaoLinked == true) {
      entered = true;
      return;
    }
    final kakaoToken = await _getKakaoToken();
    if (kakaoToken == null) return;
    late final ServiceSession linked;
    try {
      linked = await _api.kakao(kakaoToken, serviceToken: current?.token);
    } on ApiException catch (error) {
      linkConflict = error.statusCode == 409;
      rethrow;
    }
    if (current != null && linked.userId != current.userId) {
      throw const ApiException(ApiErrorType.badResponse, '계정 연결을 확인할 수 없어요.');
    }
    await _save(linked);
    entered = true;
  });

  Future<void> signInExistingKakao() => _run(() async {
    final kakaoToken = await _getKakaoToken();
    if (kakaoToken == null) return;
    await _save(await _api.kakao(kakaoToken));
    entered = true;
  });

  Future<void> logout() => _run(() async {
    final current = session;
    if (current == null || !current.kakaoLinked) return;
    try {
      await _api.revoke(current.token);
    } on ApiException catch (error) {
      if (error.statusCode != 401) rethrow;
    }
    await _storage.delete(key: _storageKey);
    await _storage.delete(key: _legacyStorageKey);
    _sessionNeedsSaving = false;
    session = null;
    entered = false;
  });

  void continueOffline() {
    if (busy) return;
    message = null;
    entered = true;
    notifyListeners();
  }

  Future<ServiceSession?> _restoreSavedSession() async {
    final legacyToken = await _storage.read(key: _legacyStorageKey);
    final savedToken =
        session?.token ?? await _storage.read(key: _storageKey) ?? legacyToken;
    if (savedToken == null) return null;
    try {
      session = await _api.current(savedToken);
      if (await _storage.read(key: _storageKey) == null) await _save(session!);
      if (_sessionNeedsSaving) await _save(session!);
      final expiresSoon =
          session!.expiresAt.difference(DateTime.now()) <
          const Duration(days: 1);
      if (expiresSoon) {
        ServiceSession? renewed;
        try {
          renewed = await _api.refresh(savedToken);
        } on ApiException catch (error) {
          if (!error.canRetry) rethrow;
        }
        if (renewed != null) await _save(renewed);
      }
    } on ApiException catch (error) {
      if (error.statusCode != 401) rethrow;
      session = null;
      _sessionNeedsSaving = false;
      await _storage.delete(key: _storageKey);
      if (legacyToken != null && legacyToken != savedToken) {
        return _restoreSavedSession();
      }
      await _storage.delete(key: _legacyStorageKey);
      message = '이용 시간이 만료됐어요. 다시 시작해 주세요.';
    }
    return session;
  }

  Future<void> _save(ServiceSession value) async {
    session = value;
    _sessionNeedsSaving = true;
    await _storage.write(key: _storageKey, value: value.token);
    await _storage.delete(key: _legacyStorageKey);
    _sessionNeedsSaving = false;
    message = null;
  }

  Future<void> _run(Future<void> Function() action) async {
    if (busy) return;
    busy = true;
    linkConflict = false;
    message = null;
    notifyListeners();
    try {
      await action();
    } on ApiException catch (error) {
      message = error.message;
    } on PlatformException {
      message = '기기에 로그인 정보를 저장하거나 불러올 수 없어요.';
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  static bool _cancelled(Object error) =>
      (error is PlatformException && error.code == 'CANCELED') ||
      (error is KakaoClientException &&
          error.reason == ClientErrorCause.cancelled);

  static Future<String?> _loginWithKakao() async {
    try {
      if (await isKakaoTalkInstalled()) {
        try {
          return (await UserApi.instance.loginWithKakaoTalk()).accessToken;
        } on Exception catch (error) {
          if (_cancelled(error)) return null;
        }
      }
      return (await UserApi.instance.loginWithKakaoAccount()).accessToken;
    } on Exception catch (error) {
      if (_cancelled(error)) return null;
      throw const ApiException(
        ApiErrorType.unknown,
        '카카오 로그인을 완료하지 못했어요. 다시 시도해 주세요.',
      );
    } finally {
      await TokenManagerProvider.instance.manager.clear();
    }
  }
}
