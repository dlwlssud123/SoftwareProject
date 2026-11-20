import '../core/network/api_client.dart';
import '../core/network/api_exception.dart';
import '../models/welfare.dart';
import '../services/account.dart';

class WelfareApi {
  WelfareApi(this._client, this._account);
  final ApiClient _client;
  final Account _account;

  Future<T> _private<T>(Future<T> Function(String token) send) async {
    final owner = _account.session?.userId;
    if (owner == null) throw _authRequired();
    final result = await _account.request(send);
    // A delayed response from a previous account must not reach the next user.
    if (_account.session?.userId != owner) throw _authRequired();
    return result;
  }

  static ApiException _authRequired() => const ApiException(
    ApiErrorType.badResponse,
    '저장한 복지와 메모는 로그인 후 이용해 주세요. 설정에서 계정을 확인해 주세요.',
    statusCode: 401,
    code: 'AUTH_REQUIRED',
  );

  static T _read<T>(Object? body, T Function(Map<String, dynamic>) parse) {
    try {
      return parse(
        (body as Map<String, dynamic>)['data'] as Map<String, dynamic>,
      );
    } on TypeError {
      throw const FormatException('Invalid welfare response');
    } on ArgumentError {
      throw const FormatException('Invalid welfare response');
    }
  }

  static String _path(String id) {
    if (!RegExp(r'^WLF[0-9]{1,61}$').hasMatch(id)) {
      throw const ApiException(ApiErrorType.badResponse, '복지 정보를 다시 선택해 주세요.');
    }
    return id;
  }

  Future<WelfareResults> recommend({
    required int age,
    required String region,
    String? district,
    bool? livesAlone,
  }) => _client.post(
    '/api/v1/welfare/recommendations',
    followRedirects: false,
    body: {
      'age': age,
      'region': region,
      if (district != null && district.trim().isNotEmpty)
        'district': district.trim(),
      'lives_alone': ?livesAlone,
      'limit': 10,
    },
    parse: (body) => _read(body, WelfareResults.fromJson),
  );

  Future<WelfareService> detail(String id) => _client.get(
    '/api/v1/welfare/${_path(id)}',
    parse: (body) => _read(body, WelfareService.fromJson),
  );

  Future<SavedWelfarePage> saved({int offset = 0}) => _private(
    (token) => _client.get(
      '/api/v1/saved-welfare',
      token: token,
      query: {'limit': 20, 'offset': offset},
      parse: (body) => _read(body, SavedWelfarePage.fromJson),
    ),
  );

  Future<bool> isSaved(String id) => _private(
    (token) => _client.get(
      '/api/v1/saved-welfare/${_path(id)}',
      token: token,
      parse: (body) => _read(body, (data) => data['saved'] as bool),
    ),
  );

  Future<bool> save(String id) => _private(
    (token) => _client.put(
      '/api/v1/saved-welfare/${_path(id)}',
      token: token,
      parse: (body) => _read(body, (data) => data['saved'] as bool),
    ),
  );

  Future<void> remove(String id) => _private(
    (token) =>
        _client.delete('/api/v1/saved-welfare/${_path(id)}', token: token),
  );

  Future<WelfareNote> note(String id) => _private(
    (token) => _client.get(
      '/api/v1/saved-welfare/${_path(id)}/note',
      token: token,
      parse: (body) => _read(body, WelfareNote.fromJson),
    ),
  );

  Future<WelfareNote> updateNote(String id, String text) => _private(
    (token) => _client.patch(
      '/api/v1/saved-welfare/${_path(id)}/note',
      token: token,
      body: {'note': text.trim().isEmpty ? null : text.trim()},
      parse: (body) => _read(body, WelfareNote.fromJson),
    ),
  );
}
