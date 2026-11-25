import 'package:dio/dio.dart';
import '../core/network/api_client.dart';
import '../models/health_video.dart';

class HealthVideoApi {
  HealthVideoApi(this._client);
  final ApiClient _client;
  static T _read<T>(Object? value, T Function(Map<String, dynamic>) parse) {
    try {
      return parse(
        (value as Map<String, dynamic>)['data'] as Map<String, dynamic>,
      );
    } on TypeError {
      throw const FormatException('Invalid video response');
    } on ArgumentError {
      throw const FormatException('Invalid video response');
    }
  }

  Future<HealthVideoPage> list({
    VideoTopic? topic,
    int offset = 0,
    CancelToken? cancelToken,
  }) => _client.get(
    '/api/v1/health-videos',
    query: {
      'limit': 20,
      'offset': offset,
      if (topic != null) 'topic': topic.value,
    },
    cancelToken: cancelToken,
    parse: (body) => _read(body, HealthVideoPage.fromJson),
  );
  Future<HealthVideo> detail(String id, {CancelToken? cancelToken}) {
    if (!RegExp(r'^[a-z0-9]+(?:-[a-z0-9]+)*$').hasMatch(id) || id.length > 60) {
      throw const FormatException('Invalid video identifier');
    }
    return _client.get(
      '/api/v1/health-videos/$id',
      cancelToken: cancelToken,
      parse: (body) => _read(body, (row) {
        final video = HealthVideo.fromJson(row);
        if (video.id != id) throw const FormatException('Wrong video');
        return video;
      }),
    );
  }
}
