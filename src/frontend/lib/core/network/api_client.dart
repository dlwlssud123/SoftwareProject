import 'package:dio/dio.dart';

import 'api_config.dart';
import '../../services/usage_recorder.dart';
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
          ) {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          try {
            final recorder = UsageRecorder.current;
            recorder?.changed();
            final route = usageRoute(options.path, options.method);
            if (route != null &&
                recorder != null &&
                recorder.enabled() &&
                recorder.token() != null) {
              options.extra['usage-watch'] = Stopwatch()..start();
              recorder.record(
                'request_started',
                route.$1,
                action: route.$2,
                outcome: 'started',
              );
              options.extra['usage-owner'] = recorder.token();
              options.extra['usage-generation'] = recorder.generation;
            }
          } catch (_) {
            /* Optional instrumentation must not interrupt a request. */
          }
          handler.next(options);
        },
      ),
    );
  }

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

  Future<void> delete(String path, {required String token, Object? body}) =>
      _send<void>(
        () => _dio.delete<Object?>(path, data: body, options: _options(token)),
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

  void _usage(
    RequestOptions options,
    Response<Object?>? response, {
    String? errorKind,
  }) {
    try {
      final recorder = UsageRecorder.current;
      recorder?.changed();
      if (recorder == null ||
          recorder.token() != options.extra['usage-owner'] ||
          recorder.generation != options.extra['usage-generation']) {
        return;
      }
      final watch = options.extra['usage-watch'];
      final route = usageRoute(options.path, options.method);
      if (watch is! Stopwatch || route == null) return;
      watch.stop();
      // Inspect only typed counters and server-issued request IDs, never bodies or messages.
      final envelope = response?.data;
      final data = envelope is Map ? envelope['data'] : null;
      final items = data is Map ? data['items'] : null;
      final kind = data is Map ? data['answer_status'] : null;
      final requestId = response?.headers.value('x-request-id');
      UsageRecorder.current?.record(
        'request_finished',
        route.$1,
        action: route.$2,
        outcome: errorKind == null
            ? 'success'
            : errorKind == 'cancelled'
            ? 'cancelled'
            : 'failure',
        durationMs: watch.elapsedMilliseconds,
        errorKind: errorKind,
        requestId: requestId,
        resultCount: items is List ? items.length : null,
        resultKind: kind is String ? kind : null,
      );
    } catch (_) {
      /* Never let telemetry replace the result of a service request. */
    }
  }

  Future<T> _send<T>(
    Future<Response<Object?>> Function() request,
    T Function(Object? json) parse,
  ) async {
    Response<Object?>? response;
    try {
      response = await request();
      final result = parse(response.data);
      _usage(response.requestOptions, response);
      return result;
    } on DioException catch (error) {
      final converted = ApiException.fromDio(error);
      final status = error.response?.statusCode;
      final kind = switch (status) {
        401 => 'unauthorized',
        403 => 'forbidden',
        409 => 'conflict',
        422 => 'validation',
        _ => switch (converted.type) {
          ApiErrorType.network => 'network',
          ApiErrorType.timeout => 'timeout',
          ApiErrorType.server => 'server',
          ApiErrorType.cancelled => 'cancelled',
          ApiErrorType.badResponse => 'bad_response',
          _ => 'unknown',
        },
      };
      _usage(error.requestOptions, error.response, errorKind: kind);
      throw converted;
    } on FormatException {
      if (response != null) {
        _usage(response.requestOptions, response, errorKind: 'bad_response');
      }
      throw const ApiException(ApiErrorType.badResponse, '서버 응답 형식이 올바르지 않아요.');
    }
  }
}
