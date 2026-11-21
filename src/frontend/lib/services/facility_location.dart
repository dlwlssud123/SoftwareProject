import 'dart:async';
import 'package:geolocator/geolocator.dart';

class FacilityLocationException implements Exception {
  const FacilityLocationException(this.message, {this.cancelled = false});
  final String message;
  final bool cancelled;
}

/// One user-initiated lookup. Cancellation also prevents late permission grants
/// from starting location updates after the screen has gone away.
class FacilityLocationLookup {
  FacilityLocationLookup({GeolocatorPlatform? platform})
    : _platform = platform ?? GeolocatorPlatform.instance;
  final GeolocatorPlatform _platform;
  final _result = Completer<Position>();
  StreamSubscription<Position>? _subscription;
  Timer? _timer;
  bool _started = false;
  bool get _done => _result.isCompleted;

  Future<Position> start() {
    if (!_started) {
      _started = true;
      _start();
    }
    return _result.future;
  }

  void cancel() =>
      _fail(const FacilityLocationException('위치 찾기를 취소했어요.', cancelled: true));

  void _stop() {
    _timer?.cancel();
    _subscription?.cancel();
  }

  void _fail(FacilityLocationException error) {
    if (_done) return;
    _result.completeError(error);
    _stop();
  }

  Future<void> _start() async {
    try {
      final enabled = await _platform.isLocationServiceEnabled();
      if (_done) return;
      if (!enabled) {
        _fail(
          const FacilityLocationException(
            '휴대폰 위치 기능이 꺼져 있어요. 아래 지역 검색을 이용해 주세요.',
          ),
        );
        return;
      }
      var permission = await _platform.checkPermission();
      if (_done) return;
      if (permission == LocationPermission.denied) {
        permission = await _platform.requestPermission();
      }
      if (_done) return;
      if (permission != LocationPermission.whileInUse &&
          permission != LocationPermission.always) {
        _fail(
          const FacilityLocationException('위치 권한 없이도 아래에서 지역을 선택해 찾을 수 있어요.'),
        );
        return;
      }
      _timer = Timer(
        const Duration(seconds: 15),
        () => _fail(
          const FacilityLocationException(
            '위치를 찾는 데 시간이 걸려요. 아래 지역 검색을 이용해 주세요.',
          ),
        ),
      );
      _subscription = _platform
          .getPositionStream(
            locationSettings: const LocationSettings(
              accuracy: LocationAccuracy.medium,
            ),
          )
          .listen(
            (point) {
              if (_done) return;
              final age = DateTime.now().toUtc().difference(
                point.timestamp.toUtc(),
              );
              if (!point.latitude.isFinite ||
                  !point.longitude.isFinite ||
                  point.latitude.abs() > 90 ||
                  point.longitude.abs() > 180 ||
                  !point.accuracy.isFinite ||
                  point.accuracy < 0 ||
                  age > const Duration(minutes: 2) ||
                  age < const Duration(minutes: -1)) {
                return; // Wait for a current, valid fix instead of reusing an old one.
              }
              if (point.accuracy > 5000) {
                _fail(
                  const FacilityLocationException(
                    '위치 오차가 커서 가까운 순서를 확인하기 어려워요. 지역으로 찾아 주세요.',
                  ),
                );
                return;
              }
              _result.complete(point);
              _stop();
            },
            onError: (Object _) => _fail(
              const FacilityLocationException(
                '위치를 확인하지 못했어요. 아래 지역 검색을 이용해 주세요.',
              ),
            ),
            onDone: () {
              if (!_done) {
                _fail(
                  const FacilityLocationException(
                    '위치를 확인하지 못했어요. 아래 지역 검색을 이용해 주세요.',
                  ),
                );
              }
            },
          );
      if (_done) _subscription?.cancel();
    } on Exception {
      _fail(
        const FacilityLocationException('위치를 확인하지 못했어요. 아래 지역 검색을 이용해 주세요.'),
      );
    }
  }
}
