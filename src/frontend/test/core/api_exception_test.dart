import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:valueflow/core/network/api_exception.dart';

void main() {
  final options = RequestOptions(path: '/test');

  DioException dioError(DioExceptionType type, {int? status, Object? data}) {
    return DioException(
      requestOptions: options,
      type: type,
      response: status == null
          ? null
          : Response(requestOptions: options, statusCode: status, data: data),
    );
  }

  test('타임아웃은 재시도 가능한 timeout 오류가 된다', () {
    final error = ApiException.fromDio(
      dioError(DioExceptionType.receiveTimeout),
    );
    expect(error.type, ApiErrorType.timeout);
    expect(error.canRetry, isTrue);
  });

  test('연결 실패는 network 오류가 된다', () {
    final error = ApiException.fromDio(
      dioError(DioExceptionType.connectionError),
    );
    expect(error.type, ApiErrorType.network);
    expect(error.canRetry, isTrue);
  });

  test('5xx 응답은 server 오류가 된다', () {
    final error = ApiException.fromDio(
      dioError(DioExceptionType.badResponse, status: 503),
    );
    expect(error.type, ApiErrorType.server);
    expect(error.statusCode, 503);
    expect(error.canRetry, isTrue);
  });

  test('4xx 응답은 서버가 보낸 메시지를 쓴다', () {
    final error = ApiException.fromDio(
      dioError(
        DioExceptionType.badResponse,
        status: 400,
        data: {'detail': '나이를 입력해 주세요'},
      ),
    );
    expect(error.type, ApiErrorType.badResponse);
    expect(error.message, '나이를 입력해 주세요');
    expect(error.canRetry, isFalse);
  });
}
