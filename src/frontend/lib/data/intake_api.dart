import 'dart:convert';
import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../core/network/api_client.dart';
import '../core/network/api_exception.dart';
import '../models/intake.dart';
import '../services/account.dart';

class IntakeApi {
  IntakeApi(
    this._client,
    this._account,
    this._storage, {
    required String serverOrigin,
  }) : _scope = 'pending-intake:$serverOrigin';
  final ApiClient _client;
  final Account _account;
  final FlutterSecureStorage _storage;
  final String _scope;
  Future<PendingIntake>? _preparing;

  Future<PendingIntake> prepare(
    DateTime eatenAt,
    List<FoodSelection> items,
  ) async {
    final chosen = List<FoodSelection>.unmodifiable(items);
    if (chosen.isEmpty ||
        chosen.length > 30 ||
        chosen.any(
          (item) =>
              !item.amount.isFinite ||
              item.amount <= 0 ||
              item.amount > 10000 ||
              !{'g', 'mL', '인분'}.contains(item.unit),
        )) {
      throw const ApiException(
        ApiErrorType.badResponse,
        '음식과 먹은 양을 다시 확인해 주세요.',
      );
    }
    final previous = _preparing;
    if (previous != null) {
      final pending = await previous;
      _checkOwner(pending.owner);
      final body = {
        'eaten_at': eatenAt.toUtc().toIso8601String(),
        'items': chosen.map((item) => item.toJson()).toList(),
      };
      if (jsonEncode(body) != jsonEncode(pending.body)) {
        throw const ApiException(
          ApiErrorType.badResponse,
          '먼저 이전 식사의 저장을 확인해 주세요.',
        );
      }
      return pending;
    }
    final task = _prepare(eatenAt, chosen);
    _preparing = task;
    try {
      return await task;
    } finally {
      if (identical(_preparing, task)) _preparing = null;
    }
  }

  Future<T> _private<T>(Future<T> Function(String token) send) {
    // Never turn an expired/offline user's retry into a new guest identity.
    if (_account.session == null) {
      return Future.error(
        const ApiException(
          ApiErrorType.badResponse,
          '식사 기록은 로그인 후 사용할 수 있어요. 설정에서 계정을 확인해 주세요.',
          statusCode: 401,
          code: 'AUTH_REQUIRED',
        ),
      );
    }
    return _account.request(send);
  }

  Future<FoodPage> foods(String query, {int offset = 0}) => _client.get(
    '/api/v1/foods',
    query: {'q': query.trim(), 'limit': 20, 'offset': offset},
    parse: (body) => _read(
      body,
      (data) => FoodPage(
        [
          for (final row in data['items'] as List)
            FoodChoice.fromJson(intakeMap(row)),
        ],
        data['total'] as int,
        data['offset'] as int,
      ),
    ),
  );

  Future<IntakePreview> preview(List<FoodSelection> items) => _client.post(
    '/api/v1/nutrition/calculate',
    body: {'items': items.map((item) => item.toJson()).toList()},
    parse: (body) => _read(body, IntakePreview.fromJson),
  );

  Future<IntakePage> history(DateTime day, {int offset = 0}) => _private(
    (token) => _client.get(
      '/api/v1/meals',
      token: token,
      query: {'day': intakeDate(day), 'limit': 20, 'offset': offset},
      parse: (body) => _read(
        body,
        (data) => IntakePage(
          [
            for (final row in data['items'] as List)
              SavedIntake.fromJson(intakeMap(row)),
          ],
          data['total'] as int,
          data['offset'] as int,
        ),
      ),
    ),
  );

  Future<SavedIntake> detail(String id) => _private(
    (token) => _client.get(
      '/api/v1/meals/${Uri.encodeComponent(id)}',
      token: token,
      parse: (body) => _read(body, SavedIntake.fromJson),
    ),
  );

  Future<SavedIntake> update(
    SavedIntake original,
    DateTime eatenAt, {
    List<FoodSelection>? items,
  }) => _private(
    (token) => _client.patch(
      '/api/v1/meals/${Uri.encodeComponent(original.id)}',
      token: token,
      body: {
        'expected_version': original.version,
        'eaten_at': eatenAt.toUtc().toIso8601String(),
        if (items != null) 'items': items.map((item) => item.toJson()).toList(),
      },
      parse: (body) => _read(body, SavedIntake.fromJson),
    ),
  );

  Future<void> remove(SavedIntake original) => _private((token) async {
    try {
      await _client.delete(
        '/api/v1/meals/${Uri.encodeComponent(original.id)}?version=${original.version}',
        token: token,
      );
    } on ApiException catch (error) {
      if (error.statusCode != 404) {
        rethrow; // A lost deletion acknowledgement may be retried safely.
      }
    }
  });

  Future<PendingIntake?> pending() =>
      _private((_) => _readPending(_account.session!.userId));

  Future<void> clearBrokenPendingAfterReview() => _private((_) async {
    final owner = _account.session!.userId;
    try {
      await _storage.delete(key: '$_scope:$owner');
    } on Exception {
      throw const ApiException(
        ApiErrorType.badResponse,
        '이전 저장 요청을 정리하지 못했어요. 다시 시도해 주세요.',
      );
    }
    _checkOwner(owner);
  });

  Future<PendingIntake?> _readPending(String owner) async {
    try {
      final raw = await _storage.read(key: '$_scope:$owner');
      _checkOwner(owner);
      if (raw == null) return null;
      final pending = PendingIntake.fromStorage(intakeMap(jsonDecode(raw)));
      if (pending.owner != owner) {
        throw const FormatException('Wrong pending owner');
      }
      return pending;
    } on ApiException {
      rethrow;
    } on Exception {
      throw const ApiException(
        ApiErrorType.badResponse,
        '이전 식사의 저장 요청을 확인하지 못했어요. 저장한 식사를 확인하고 다시 시도해 주세요.',
      );
    } on TypeError {
      throw const ApiException(
        ApiErrorType.badResponse,
        '이전 식사의 저장 요청을 읽지 못했어요. 저장한 식사를 먼저 확인해 주세요.',
      );
    }
  }

  Future<PendingIntake> _prepare(DateTime eatenAt, List<FoodSelection> items) =>
      _private((_) async {
        final owner = _account.session!.userId;
        final random = Random.secure();
        final attempt = PendingIntake(
          owner,
          List.generate(
            16,
            (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0'),
          ).join(),
          eatenAt.toUtc(),
          List.unmodifiable(items),
        );
        final previous = await _readPending(owner);
        if (previous != null) {
          if (jsonEncode(previous.body) != jsonEncode(attempt.body)) {
            throw const ApiException(
              ApiErrorType.badResponse,
              '먼저 이전 식사의 저장을 확인해 주세요.',
            );
          }
          return previous;
        }
        try {
          await _storage.write(
            key: '$_scope:$owner',
            value: jsonEncode(attempt.toStorage()),
          );
        } on Exception {
          throw const ApiException(
            ApiErrorType.badResponse,
            '기기에 저장 요청을 보관하지 못했어요. 다시 시도해 주세요.',
          );
        }
        _checkOwner(owner);
        return attempt;
      });

  Future<SavedIntake> submit(PendingIntake pending) => _private((token) async {
    _checkOwner(pending.owner);
    late SavedIntake saved;
    try {
      saved = await _client.post(
        '/api/v1/meals',
        token: token,
        body: pending.body,
        idempotencyKey: pending.key,
        parse: (body) => _read(
          body,
          (data) => SavedIntake.fromJson(intakeMap(data['meal'])),
        ),
      );
    } on ApiException catch (error) {
      // Only definitive API rejection permits editing; transport/parse failures keep the same request.
      if ({
        'FOOD_NOT_FOUND',
        'FOOD_REVISION_CHANGED',
        'PORTION_NOT_RECORDABLE',
        'VALIDATION_ERROR',
        'MEAL_ALREADY_DELETED',
      }.contains(error.code)) {
        await _clear(pending);
      }
      rethrow;
    }
    try {
      await _clear(pending);
    } on ApiException {
      // The server acknowledgement is authoritative. A retained receipt can replay, never duplicate.
    }
    _checkOwner(pending.owner);
    return saved;
  });

  Future<void> _clear(PendingIntake pending) async {
    try {
      final current = await _readPending(pending.owner);
      if (current?.key == pending.key) {
        await _storage.delete(key: '$_scope:${pending.owner}');
      }
    } on ApiException {
      rethrow;
    } on Exception {
      throw const ApiException(
        ApiErrorType.badResponse,
        '저장 요청 확인 정보를 정리하지 못했어요. 다시 시도해 주세요.',
      );
    }
  }

  void _checkOwner(String owner) {
    if (_account.session?.userId != owner) {
      throw const ApiException(
        ApiErrorType.badResponse,
        '계정이 바뀌었어요. 저장한 식사부터 다시 확인해 주세요.',
      );
    }
  }

  static T _read<T>(Object? body, T Function(Map<String, dynamic>) decode) {
    try {
      return decode(intakeMap(intakeMap(body)['data']));
    } on TypeError {
      throw const FormatException('Invalid intake response');
    } on ArgumentError {
      throw const FormatException('Invalid intake value');
    }
  }
}
