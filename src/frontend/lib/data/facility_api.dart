import 'package:dio/dio.dart';
import '../core/network/api_client.dart';
import '../models/facility.dart';

class FacilityApi {
  FacilityApi(this._client);
  final ApiClient _client;

  static T _read<T>(Object? body, T Function(Map<String, dynamic>) parse) {
    try {
      return parse(
        (body as Map<String, dynamic>)['data'] as Map<String, dynamic>,
      );
    } on TypeError {
      throw const FormatException('Invalid facility response');
    } on ArgumentError {
      throw const FormatException('Invalid facility response');
    }
  }

  Future<FacilityPage> search({
    required String region,
    String? district,
    String? query,
    int offset = 0,
    CancelToken? cancelToken,
  }) => _client.get(
    '/api/v1/meal-facilities',
    query: {
      'region': region,
      if (district != null && district.isNotEmpty) 'district': district,
      if (query != null && query.isNotEmpty) 'q': query,
      'limit': 20,
      'offset': offset,
    },
    cancelToken: cancelToken,
    parse: (body) => _read(body, FacilityPage.fromJson),
  );

  Future<FacilityPage> nearby({
    required double latitude,
    required double longitude,
    required double radiusKm,
    String? region,
    String? district,
    String? query,
    int offset = 0,
    CancelToken? cancelToken,
  }) => _client.post(
    '/api/v1/meal-facilities/nearby',
    followRedirects: false,
    cancelToken: cancelToken,
    body: {
      'latitude': latitude,
      'longitude': longitude,
      'radius_km': radiusKm,
      'region': ?region,
      if (region != null && district != null && district.isNotEmpty)
        'district': district,
      if (query != null && query.isNotEmpty) 'q': query,
      'limit': 20,
      'offset': offset,
    },
    parse: (body) => _read(body, FacilityPage.fromJson),
  );

  Future<MealFacility> detail(String id, {CancelToken? cancelToken}) {
    if (!facilityIdPattern.hasMatch(id)) {
      throw const FormatException('Invalid facility ID');
    }
    return _client.get(
      '/api/v1/meal-facilities/$id',
      cancelToken: cancelToken,
      parse: (body) => _read(body, MealFacility.fromJson),
    );
  }
}
