import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../core/network/api_client.dart';
import '../core/network/api_exception.dart';
import '../models/community.dart';
import '../models/topic_request.dart' show topicMap, topicUuid;
import '../services/account.dart';

class CommunityApi {
  CommunityApi(
    this._client,
    this._account,
    this._storage, {
    required String serverOrigin,
  }) : _scope = 'pending-community:$serverOrigin';
  final ApiClient _client;
  final Account _account;
  final FlutterSecureStorage _storage;
  final String _scope;
  Future<void> _tail = Future.value();
  static const _root = '/api/v1/community';
  String? get owner => _account.session?.userId;
  Listenable get identity => _account;
  void _check(String user) {
    if (owner != user) {
      throw const ApiException(
        ApiErrorType.badResponse,
        '계정이 바뀌었어요. 커뮤니티를 다시 열어 주세요.',
        statusCode: 401,
      );
    }
  }

  Future<T> _private<T>(Future<T> Function(String token) send) async {
    final user = owner;
    if (user == null) {
      throw const ApiException(
        ApiErrorType.badResponse,
        '커뮤니티는 로그인 후 이용해 주세요.',
        statusCode: 401,
      );
    }
    final result = await _account.request(send);
    _check(user);
    return result;
  }

  static T _read<T>(Object? value, T Function(Map<String, dynamic>) parse) {
    try {
      return parse(topicMap(topicMap(value)['data']));
    } on TypeError {
      throw const FormatException('Invalid community response');
    } on ArgumentError {
      throw const FormatException('Invalid community response');
    }
  }

  Future<CommunityPage<CommunityPost>> posts({
    bool mine = false,
    CommunityCategory? category,
    int offset = 0,
  }) => _private(
    (token) => _client.get(
      '$_root/posts${mine ? '/mine' : ''}',
      token: token,
      query: {
        'limit': 20,
        'offset': offset,
        if (!mine && category != null) 'category': category.value,
      },
      parse: (body) => _read(
        body,
        (row) => CommunityPage.fromJson(row, CommunityPost.fromJson),
      ),
    ),
  );
  Future<CommunityPost> detail(String id) => _private(
    (token) => _client.get(
      '$_root/posts/${topicUuid(id)}',
      token: token,
      parse: (body) => _read(body, CommunityPost.fromJson),
    ),
  );
  Future<void> remove(CommunityPost post) => _private(
    (token) => _client.delete(
      '$_root/posts/${topicUuid(post.id)}',
      token: token,
      body: {'expected_version': post.version},
    ),
  );
  Future<void> report(String id, String reason) => _private(
    (token) => _client.post(
      '$_root/posts/${topicUuid(id)}/reports',
      token: token,
      body: {'reason': reason, 'note': ''},
      parse: (body) => _read(body, (row) {
        topicUuid(row['id']);
        if (!const [
          'received',
          'dismissed',
          'actioned',
        ].contains(row['status'])) {
          throw const FormatException('Invalid report receipt');
        }
      }),
    ),
  );
  Future<void> block(String postId) => _private(
    (token) => _client.post(
      '$_root/posts/${topicUuid(postId)}/block-author',
      token: token,
      parse: (body) {
        _read(body, CommunityBlock.fromJson);
      },
    ),
  );
  Future<CommunityPage<CommunityBlock>> blocks({int offset = 0}) => _private(
    (token) => _client.get(
      '$_root/blocks',
      token: token,
      query: {'limit': 20, 'offset': offset},
      parse: (body) => _read(
        body,
        (row) => CommunityPage.fromJson(row, CommunityBlock.fromJson),
      ),
    ),
  );
  Future<void> unblock(String id) => _private(
    (token) => _client.delete('$_root/blocks/${topicUuid(id)}', token: token),
  );

  // Serialise receipt access so a late response cannot clear a newer submission.
  Future<T> _receipt<T>(String user, Future<T> Function() action) {
    final task = _tail.then((_) async {
      _check(user);
      return action();
    });
    _tail = task.then<void>((_) {}, onError: (Object _, StackTrace _) {});
    return task;
  }

  Future<PendingCommunityPost?> pending() => _private((_) {
    final user = owner!;
    return _receipt(user, () => _pending(user));
  });
  Future<PendingCommunityPost?> _pending(String user) async {
    try {
      final raw = await _storage.read(key: '$_scope:$user');
      _check(user);
      if (raw == null) return null;
      final result = PendingCommunityPost.fromJson(topicMap(jsonDecode(raw)));
      if (result.owner != user) throw const FormatException('Wrong owner');
      return result;
    } on ApiException {
      rethrow;
    } on Object {
      throw const ApiException(
        ApiErrorType.badResponse,
        '이전 글의 전송 정보를 읽지 못했어요. 앱을 다시 열어 주세요.',
      );
    }
  }

  static String _uuid() {
    final random = Random.secure();
    final bytes = List.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
  }

  Future<PendingCommunityPost> prepare(
    CommunityCategory category,
    String title,
    String body,
  ) => _private((_) {
    final user = owner!;
    return _receipt(user, () async {
      final previous = await _pending(user);
      if (previous != null) {
        if (previous.category != category ||
            previous.title != title.trim() ||
            previous.body != body.trim()) {
          throw const ApiException(
            ApiErrorType.badResponse,
            '이전 글의 전송 결과를 먼저 확인해 주세요. 글쓰기를 다시 열면 확인할 수 있어요.',
          );
        }
        return previous;
      }
      final result = PendingCommunityPost(
        user,
        _uuid(),
        category,
        communityText(title.trim(), 60),
        communityText(body.trim(), 2000),
      );
      await _storage.write(
        key: '$_scope:$user',
        value: jsonEncode(result.storage),
      );
      _check(user);
      return result;
    });
  });
  Future<void> _clearPending(PendingCommunityPost pending) =>
      _receipt(pending.owner, () async {
        final current = await _pending(pending.owner);
        if (current?.submissionId == pending.submissionId) {
          await _storage.delete(key: '$_scope:${pending.owner}');
        }
        _check(pending.owner);
      });

  Future<CommunityPost> submit(PendingCommunityPost pending) async {
    _check(pending.owner);
    final post =
        await _private(
          (token) => _client.post(
            '$_root/posts',
            token: token,
            body: pending.payload,
            parse: (body) => _read(body, (row) {
              if (row['replayed'] is! bool) {
                throw const FormatException('Invalid replay state');
              }
              final post = CommunityPost.fromJson(topicMap(row['post']));
              if (!post.isMine ||
                  post.category != pending.category ||
                  post.title != pending.title ||
                  post.body != pending.body) {
                throw const FormatException('Wrong submitted post');
              }
              return post;
            }),
          ),
        ).onError<ApiException>((error, stack) async {
          // A deleted submission has a terminal receipt and must never be recreated.
          if (error.statusCode == 404 && error.code == 'COMMUNITY_NOT_FOUND') {
            await _clearPending(pending);
          }
          Error.throwWithStackTrace(error, stack);
        });
    // The confirmed server result remains valid if local receipt cleanup fails.
    try {
      await _clearPending(pending);
    } on Object {
      _check(pending.owner);
    }
    return post;
  }
}
