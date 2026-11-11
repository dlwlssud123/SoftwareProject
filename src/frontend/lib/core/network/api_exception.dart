import 'package:dio/dio.dart';

/// 화면에서 구분해서 보여줄 오류 종류.
enum ApiErrorType { network, timeout, server, badResponse, cancelled, unknown }

/// 앱 전체에서 공통으로 쓰는 통신 오류.
///
/// 화면은 dio 오류를 직접 다루지 않고 이 클래스의 [message]와
/// [canRetry]만 보고 안내 문구와 재시도 버튼을 결정한다.
class ApiException implements Exception {
  const ApiException(
    this.type,
    this.message, {
    this.statusCode,
    this._retryable,
  });

  final ApiErrorType type;
  final String message;
  final int? statusCode;
  final bool? _retryable;

  /// 잠시 후 다시 시도하면 해결될 수 있는 오류인지.
  bool get canRetry =>
      _retryable ??
      (type == ApiErrorType.network ||
          type == ApiErrorType.timeout ||
          type == ApiErrorType.server);

  factory ApiException.fromDio(DioException error) {
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.transformTimeout:
        return const ApiException(
          ApiErrorType.timeout,
          '응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요.',
        );
      case DioExceptionType.connectionError:
        return const ApiException(ApiErrorType.network, '인터넷 연결을 확인해 주세요.');
      case DioExceptionType.cancel:
        return const ApiException(ApiErrorType.cancelled, '요청이 취소되었어요.');
      case DioExceptionType.badResponse:
        final status = error.response?.statusCode;
        final data = error.response?.data;
        final details = data is Map ? data['error'] : null;
        final message = details is Map ? details['message'] : null;
        final retryable = details is Map ? details['retryable'] : null;
        final isServerError = status != null && status >= 500;
        final fallback = isServerError
            ? '서버에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.'
            : _legacyMessage(data) ?? '요청을 처리하지 못했어요.';
        return ApiException(
          isServerError ? ApiErrorType.server : ApiErrorType.badResponse,
          message is String && message.trim().isNotEmpty ? message : fallback,
          statusCode: status,
          retryable: retryable is bool ? retryable : null,
        );
      case DioExceptionType.badCertificate:
      case DioExceptionType.unknown:
        return const ApiException(ApiErrorType.unknown, '알 수 없는 오류가 발생했어요.');
    }
  }

  static String? _legacyMessage(Object? data) {
    if (data is Map) {
      for (final key in const ['message', 'detail']) {
        final value = data[key];
        if (value is String && value.trim().isNotEmpty) return value;
      }
    }
    return null;
  }

  @override
  String toString() => 'ApiException($type, $statusCode): $message';
}
