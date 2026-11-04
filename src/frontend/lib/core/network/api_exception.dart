import 'package:dio/dio.dart';

/// 화면에서 구분해서 보여줄 오류 종류.
enum ApiErrorType { network, timeout, server, badResponse, cancelled, unknown }

/// 앱 전체에서 공통으로 쓰는 통신 오류.
///
/// 화면은 dio 오류를 직접 다루지 않고 이 클래스의 [message]와
/// [canRetry]만 보고 안내 문구와 재시도 버튼을 결정한다.
class ApiException implements Exception {
  const ApiException(this.type, this.message, {this.statusCode});

  final ApiErrorType type;
  final String message;
  final int? statusCode;

  /// 잠시 후 다시 시도하면 해결될 수 있는 오류인지.
  bool get canRetry =>
      type == ApiErrorType.network ||
      type == ApiErrorType.timeout ||
      type == ApiErrorType.server;

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
        return const ApiException(
          ApiErrorType.network,
          '인터넷 연결을 확인해 주세요.',
        );
      case DioExceptionType.cancel:
        return const ApiException(ApiErrorType.cancelled, '요청이 취소되었어요.');
      case DioExceptionType.badResponse:
        final status = error.response?.statusCode;
        if (status != null && status >= 500) {
          return ApiException(
            ApiErrorType.server,
            '서버에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.',
            statusCode: status,
          );
        }
        return ApiException(
          ApiErrorType.badResponse,
          _serverMessage(error.response?.data) ?? '요청을 처리하지 못했어요.',
          statusCode: status,
        );
      case DioExceptionType.badCertificate:
      case DioExceptionType.unknown:
        return const ApiException(
          ApiErrorType.unknown,
          '알 수 없는 오류가 발생했어요.',
        );
    }
  }

  /// 오류 응답 형식은 백엔드와 확정 전이라 흔한 키(message, detail)를 모두 확인한다.
  static String? _serverMessage(Object? data) {
    if (data is Map) {
      for (final key in const ['message', 'detail']) {
        final value = data[key];
        if (value is String && value.isNotEmpty) return value;
      }
    }
    return null;
  }

  @override
  String toString() => 'ApiException($type, $statusCode): $message';
}
