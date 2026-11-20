import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../core/network/api_client.dart';
import '../core/network/api_exception.dart';
import '../models/topic_request.dart';
import '../services/account.dart';

class TopicApi {
  TopicApi(
    this._client,
    this._account,
    this._storage, {
    required String serverOrigin,
  }) : _scope = 'pending-topic:$serverOrigin';
  final ApiClient _client;
  final Account _account;
  final FlutterSecureStorage _storage;
  final String _scope;
  Future<PendingTopic>? _preparing;
  String? _preparingOwner;
  Future<TopicRecord>? _mutation;
  String? _mutationScope;
  String? _mutationOwner;
  Listenable get identity => _account;
  String? get owner => _account.session?.userId;

  static const _root = '/api/v1/content-topic-requests';
  static const _auth = ApiException(
    ApiErrorType.badResponse,
    '요청 내역은 로그인 후 확인해 주세요.',
    statusCode: 401,
    code: 'AUTH_REQUIRED',
  );
  void _check(String expected) {
    if (owner != expected) throw _auth;
  }

  Future<T> _private<T>(
    Future<T> Function(String token, String user) send,
  ) async {
    final user = owner;
    if (user == null) throw _auth;
    final result = await _account.request((token) => send(token, user));
    _check(user);
    return result;
  }

  static T _read<T>(Object? body, T Function(Map<String, dynamic>) parse) {
    try {
      return parse(topicMap(topicMap(body)['data']));
    } on TypeError {
      throw const FormatException('Invalid topic response');
    } on ArgumentError {
      throw const FormatException('Invalid topic response');
    }
  }

  Future<TopicPage<TopicRecord>> history({int offset = 0}) => _private(
    (token, _) => _client.get(
      _root,
      token: token,
      query: {'limit': 20, 'offset': offset},
      parse: (body) =>
          _read(body, (row) => TopicPage.fromJson(row, TopicRecord.fromJson)),
    ),
  );
  Future<TopicRecord> detail(String id) => _private(
    (token, _) => _client.get(
      '$_root/${topicUuid(id)}',
      token: token,
      parse: (body) => _read(body, TopicRecord.fromJson),
    ),
  );
  Future<void> withdraw(String id) => _private(
    (token, _) => _client.delete('$_root/${topicUuid(id)}', token: token),
  );

  Future<TopicPage<GuideSummary>> guides({int offset = 0}) => _client.get(
    '/api/v1/life-guides',
    query: {'limit': 20, 'offset': offset},
    parse: (body) =>
        _read(body, (row) => TopicPage.fromJson(row, GuideSummary.fromJson)),
  );
  Future<GuideContent> guide(GuideSummary summary) => _client.get(
    '/api/v1/life-guides/${Uri.encodeComponent(summary.slug)}',
    parse: (body) => _read(body, (row) {
      final result = GuideContent.fromJson(row);
      if (result.summary.id != summary.id ||
          result.summary.slug != summary.slug) {
        throw const FormatException('Wrong guide');
      }
      return result;
    }),
  );

  Future<PendingTopic?> pending() => _private((_, user) => _pending(user));
  Future<PendingTopic?> _pending(String user) async {
    try {
      final raw = await _storage.read(key: '$_scope:$user');
      _check(user);
      if (raw == null) return null;
      final result = PendingTopic.fromStorage(topicMap(jsonDecode(raw)));
      if (result.owner != user) throw const FormatException('Wrong owner');
      return result;
    } on ApiException {
      rethrow;
    } on Object {
      throw const ApiException(
        ApiErrorType.badResponse,
        '이전 요청을 확인하지 못했어요. 다시 확인해 주세요.',
      );
    }
  }

  static String _submission() {
    final random = Random.secure();
    final bytes = List.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    final hex = bytes
        .map((value) => value.toRadixString(16).padLeft(2, '0'))
        .join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
  }

  Future<PendingTopic> prepare(TopicKind kind, String text) async {
    final user = owner;
    if (user == null) throw _auth;
    final topic = text.trim();
    if (topic.isEmpty ||
        topic.runes.length > 60 ||
        topic.contains(RegExp(r'[\x00-\x1f\x7f]'))) {
      throw const ApiException(
        ApiErrorType.badResponse,
        '주제를 한 줄로 60자 안에 적어 주세요.',
      );
    }
    final previous = _preparing;
    if (previous != null && _preparingOwner == user) {
      final pending = await previous;
      _check(user);
      if (pending.kind != kind || pending.topic != topic) {
        throw const ApiException(
          ApiErrorType.badResponse,
          '이전 요청을 먼저 확인하거나 취소해 주세요.',
          code: 'TOPIC_PENDING',
        );
      }
      return pending;
    }
    final task = _prepare(user, kind, topic);
    _preparing = task;
    _preparingOwner = user;
    try {
      return await task;
    } finally {
      if (identical(_preparing, task)) {
        _preparing = null;
        _preparingOwner = null;
      }
    }
  }

  Future<PendingTopic> _prepare(
    String user,
    TopicKind kind,
    String topic,
  ) async {
    final existing = await _pending(user);
    if (existing != null) {
      if (existing.kind == kind && existing.topic == topic) {
        return existing;
      }
      // A failed device cleanup must not block a later, distinct request once
      // the server has confirmed the previous submission.
      if (await lookup(existing) == null) {
        throw const ApiException(
          ApiErrorType.badResponse,
          '이전 요청을 먼저 확인하거나 취소해 주세요.',
          code: 'TOPIC_PENDING',
        );
      }
    }
    _check(user);
    final pending = PendingTopic(user, _submission(), kind, topic);
    try {
      await _storage.write(
        key: '$_scope:$user',
        value: jsonEncode(pending.toStorage()),
      );
    } on Object {
      throw const ApiException(
        ApiErrorType.badResponse,
        '요청 내용을 보관하지 못했어요. 다시 시도해 주세요.',
      );
    }
    _check(user);
    return pending;
  }

  Future<void> _clear(PendingTopic pending) async {
    _check(pending.owner);
    try {
      final current = await _pending(pending.owner);
      if (current?.submissionId == pending.submissionId) {
        await _storage.delete(key: '$_scope:${pending.owner}');
      }
      _check(pending.owner);
    } on ApiException {
      rethrow;
    } on Object {
      throw const ApiException(
        ApiErrorType.badResponse,
        '확인한 요청을 기기에서 정리하지 못했어요.',
      );
    }
  }

  Future<void> clearBrokenPendingAfterReview() => _private((_, user) async {
    try {
      await _storage.delete(key: '$_scope:$user');
    } on Object {
      throw const ApiException(
        ApiErrorType.badResponse,
        '이전 전송 정보를 정리하지 못했어요. 다시 시도해 주세요.',
      );
    }
    _check(user);
  });

  Future<TopicRecord> _mutate(
    String verb,
    PendingTopic pending,
    Future<TopicRecord> Function(String token) send,
  ) async {
    _check(pending.owner);
    final scope = '$verb:${pending.owner}:${pending.submissionId}';
    final previous = _mutation;
    if (previous != null && _mutationOwner == pending.owner) {
      if (_mutationScope != scope) {
        throw const ApiException(
          ApiErrorType.badResponse,
          '요청을 처리 중이에요. 잠시 기다려 주세요.',
        );
      }
      return previous;
    }
    final task = _private((token, _) async {
      final result = await send(token);
      _check(pending.owner);
      try {
        await _clear(pending);
      } on ApiException {
        /* The server result is authoritative; a retained receipt can only replay. */
      }
      return result;
    });
    _mutation = task;
    _mutationScope = scope;
    _mutationOwner = pending.owner;
    try {
      return await task;
    } finally {
      if (identical(_mutation, task)) {
        _mutation = null;
        _mutationScope = null;
        _mutationOwner = null;
      }
    }
  }

  Future<TopicRecord> submit(PendingTopic pending) => _mutate(
    'submit',
    pending,
    (token) => _client.post(
      _root,
      token: token,
      body: pending.body,
      parse: (body) => _read(body, (row) {
        if (row['replayed'] is! bool) {
          throw const FormatException('Missing replay state');
        }
        return TopicRecord.fromJson(topicMap(row['request']));
      }),
    ),
  );
  Future<TopicRecord> cancelPending(PendingTopic pending) => _mutate(
    'withdraw',
    pending,
    (token) => _client.post(
      '$_root/withdraw-submission',
      token: token,
      body: pending.body,
      parse: (body) => _read(body, (row) {
        final result = TopicRecord.fromJson(row);
        if (!result.withdrawn) {
          throw const FormatException('Unconfirmed withdrawal');
        }
        return result;
      }),
    ),
  );

  Future<TopicRecord?> lookup(PendingTopic pending) => _private((
    token,
    user,
  ) async {
    _check(pending.owner);
    final page = await _client.get(
      _root,
      token: token,
      query: {'submission_id': pending.submissionId},
      parse: (body) =>
          _read(body, (row) => TopicPage.fromJson(row, TopicRecord.fromJson)),
    );
    if (page.total > 1 || page.items.length > 1) {
      throw const ApiException(
        ApiErrorType.badResponse,
        '이전 요청의 처리 결과를 확인하지 못했어요.',
      );
    }
    _check(user);
    if (page.items.isEmpty) return null;
    try {
      await _clear(pending);
    } on ApiException {
      /* A known server record is enough to stop showing an uncertain send. */
    }
    return page.items.single;
  });
}
