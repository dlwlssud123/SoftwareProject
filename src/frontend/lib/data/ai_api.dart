import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../core/network/api_client.dart';
import '../core/network/api_exception.dart';
import '../models/ai.dart';
import '../models/welfare_chat.dart';
import '../models/intake.dart';
import '../services/account.dart';

class AiApi {
  AiApi(this._client, this._account);
  final ApiClient _client;
  final Account _account;

  Future<T> _send<T>(
    String path,
    Map<String, dynamic> payload,
    T Function(Map<String, dynamic>) decode,
    CancelToken cancelToken,
  ) async {
    final owner = _account.session?.userId;
    if (owner == null) {
      throw const ApiException(
        ApiErrorType.badResponse,
        '로그인 후 다시 이용해 주세요.',
        statusCode: 401,
      );
    }
    final result = await _account.request(
      (token) => _client.post<T>(
        '/api/v1/ai/$path',
        token: token,
        body: {...payload, 'allow_external_processing': true},
        receiveTimeout: const Duration(seconds: 40),
        cancelToken: cancelToken,
        parse: (body) {
          try {
            return decode(intakeMap(intakeMap(body)['data']));
          } on TypeError {
            throw const FormatException('Invalid AI response');
          }
        },
      ),
    );
    if (_account.session?.userId != owner) {
      throw const ApiException(
        ApiErrorType.badResponse,
        '계정이 바뀌었어요. 다시 시작해 주세요.',
      );
    }
    return result;
  }

  Future<String> chat(String message, CancelToken token) => _send(
    'chat',
    {'message': message.trim()},
    (row) => row['answer'] as String,
    token,
  );

  Future<WelfareChatAnswer> welfareChat(
    String message,
    CancelToken token, {
    String? region,
    String? district,
  }) => _send(
    'welfare-chat',
    {'message': message.trim(), 'region': ?region, 'district': ?district},
    WelfareChatAnswer.fromJson,
    token,
  );

  Future<PhotoRecognition> photo(Uint8List bytes, CancelToken token) {
    if (bytes.isEmpty || bytes.length > 2 * 1024 * 1024) {
      throw const ApiException(
        ApiErrorType.badResponse,
        '2MB 이하의 음식 사진을 골라 주세요.',
      );
    }
    return _send(
      'food-photo',
      {'image_base64': base64Encode(bytes)},
      PhotoRecognition.fromJson,
      token,
    );
  }

  Future<IngredientEstimate> ingredients(
    String name,
    int grams,
    CancelToken token,
  ) => _send(
    'food-ingredients',
    {'dish_name': name, 'standard_serving_grams': grams},
    IngredientEstimate.fromJson,
    token,
  );
}
