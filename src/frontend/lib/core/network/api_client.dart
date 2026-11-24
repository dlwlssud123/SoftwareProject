import 'package:dio/dio.dart';

import 'api_config.dart';
import 'api_exception.dart';

/// 백엔드와 통신하는 공통 클라이언트.
///
/// 서버 주소·타임아웃·오류 변환을 한 곳에서 관리하고,
/// 응답 JSON은 각 DTO의 fromJson으로 넘겨 변환한다.
///   final recipes = await client.get(
///     '/recipes',
///     parse: (json) => (json as List).map(...).toList(),
///   );
class ApiClient {
  ApiClient({Dio? dio, String? baseUrl})
    : _dio =
          dio ??
          Dio(
            BaseOptions(
              baseUrl: baseUrl ?? ApiConfig.baseUrl,
              connectTimeout: ApiConfig.connectTimeout,
              receiveTimeout: ApiConfig.receiveTimeout,
              headers: const {'Accept': 'application/json'},
            ),
          );

  final Dio _dio;

  Future<T> get<T>(
    String path, {
    Map<String, dynamic>? query,
    String? token,
    CancelToken? cancelToken,
    required T Function(Object? json) parse,
  }) => _send(
    () => _dio.get<Object?>(
      path,
      queryParameters: query,
      options: _options(token),
      cancelToken: cancelToken,
    ),
    parse,
  );

  Future<T> post<T>(
    String path, {
    Object? body,
    String? token,
    String? idempotencyKey,
    bool followRedirects = true,
    Duration? receiveTimeout,
    CancelToken? cancelToken,
    required T Function(Object? json) parse,
  }) => _send(
    () => _dio.post<Object?>(
      path,
      data: body,
      cancelToken: cancelToken,
      options: _options(
        token,
        followRedirects: followRedirects,
        idempotencyKey: idempotencyKey,
        receiveTimeout: receiveTimeout,
      ),
    ),
    parse,
  );

  Future<T> put<T>(
    String path, {
    Object? body,
    required String token,
    required T Function(Object? json) parse,
  }) => _send(
    () => _dio.put<Object?>(path, data: body, options: _options(token)),
    parse,
  );

  Future<void> delete(String path, {required String token}) => _send<void>(
    () => _dio.delete<Object?>(path, options: _options(token)),
    (_) {},
  );

  Future<T> patch<T>(
    String path, {
    required Object body,
    required String token,
    required T Function(Object? json) parse,
  }) => _send(
    () => _dio.patch<Object?>(path, data: body, options: _options(token)),
    parse,
  );

  Options _options(
    String? token, {
    bool followRedirects = true,
    String? idempotencyKey,
    Duration? receiveTimeout,
  }) => Options(
    receiveTimeout: receiveTimeout,
    followRedirects: followRedirects && token == null,
    headers: {
      if (token != null) 'Authorization': 'Bearer $token',
      'Idempotency-Key': ?idempotencyKey,
    },
  );

  Future<T> _send<T>(
    Future<Response<Object?>> Function() request,
    T Function(Object? json) parse,
  ) async {
    try {
      final response = await request();
      return parse(response.data);
    } on DioException catch (error) {
      throw ApiException.fromDio(error);
    } on FormatException {
      throw const ApiException(ApiErrorType.badResponse, '서버 응답 형식이 올바르지 않아요.');
    }
  }
}
