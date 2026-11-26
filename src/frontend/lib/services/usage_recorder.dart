import 'dart:async';
import 'dart:math';

/// Bounded, memory-only, opt-in telemetry. Never accepts arbitrary properties.
class UsageRecorder {
  UsageRecorder({
    required this.enabled,
    required this.token,
    required this.send,
    this.delay = const Duration(seconds: 10),
    this.appVersion = const String.fromEnvironment(
      'APP_VERSION',
      defaultValue: '0.1.0',
    ),
    this.platform = 'android',
  });
  static UsageRecorder? current;
  final bool Function() enabled;
  final String? Function() token;
  final Future<void> Function(List<Map<String, Object?>>, String) send;
  final Duration delay;
  final String appVersion, platform;
  final _queue = <Map<String, Object?>>[];
  Timer? _timer;
  bool _sending = false, _disposed = false, _enabledBefore = false;
  int generation = 0;
  String? _owner;
  int get pendingCount => _queue.length;

  void changed() {
    if (enabled() != _enabledBefore || token() != _owner) {
      generation++;
      _enabledBefore = enabled();
      _queue.clear();
      _timer?.cancel();
      _timer = null;
      _owner = token();
    }
  }

  static String _uuid() {
    final random = Random.secure();
    final bytes = List.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
  }

  void record(
    String event,
    String feature, {
    String action = 'view',
    String outcome = 'success',
    int? durationMs,
    String? errorKind,
    String? requestId,
    int? resultCount,
    String? resultKind,
    String? settingKind,
    String? settingValue,
  }) {
    if (_disposed) return;
    changed();
    final owner = token();
    if (!enabled() || owner == null) return;
    _owner = owner;
    if (_queue.length >= 100) _queue.removeAt(0);
    _queue.add({
      'event_id': _uuid(),
      'event': event,
      'feature': feature,
      'action': action,
      'outcome': outcome,
      'app_version': appVersion,
      'platform': platform,
      if (durationMs != null) 'duration_ms': durationMs.clamp(0, 3600000),
      'error_kind': ?errorKind,
      if (requestId != null &&
          RegExp(
            r'^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$',
          ).hasMatch(requestId))
        'request_id': requestId,
      if (resultCount != null) 'result_count': resultCount.clamp(0, 1000000),
      if (const [
        'generated',
        'references_only',
        'no_evidence',
      ].contains(resultKind))
        'result_kind': resultKind,
      'setting_kind': ?settingKind,
      'setting_value': ?settingValue,
    });
    _schedule();
  }

  void _schedule() {
    if (_timer == null && !_disposed && _queue.isNotEmpty && enabled()) {
      _timer = Timer(delay, () {
        _timer = null;
        unawaited(flush());
      });
    }
  }

  Future<void> flush() async {
    changed();
    final owner = token();
    if (_sending || _disposed || !enabled() || owner == null || _queue.isEmpty) {
      return;
    }
    _timer?.cancel();
    _timer = null;
    final count = min(20, _queue.length);
    final batch = _queue.take(count).toList(growable: false);
    _queue.removeRange(0, count);
    _sending = true;
    try {
      await send(batch, owner);
    } catch (_) {
      /* Analytics failure never affects app flows; no disk or infinite retries. */
    } finally {
      _sending = false;
      changed();
      _schedule();
    }
  }

  void dispose() {
    _disposed = true;
    _timer?.cancel();
    _queue.clear();
    if (identical(current, this)) current = null;
  }
}

/// Only fixed feature names leave the device; paths, query values and IDs never do.
(String, String)? usageRoute(String path, String method) {
  final p = Uri.tryParse(path)?.path ?? '';
  final write = method != 'GET';
  if (p == '/api/v1/meal/recommendations') return ('meal', 'recommend');
  if (p == '/api/v1/ai/welfare-chat') return ('welfare', 'ask');
  if (p == '/api/v1/ai/chat') return ('assistant', 'ask');
  if (const [
    '/api/v1/ai/food-photo',
    '/api/v1/ai/food-ingredients',
  ].contains(p)) {
    return ('nutrition', 'recognize');
  }
  if (p == '/api/v1/nutrition/calculate') return ('nutrition', 'calculate');
  for (final entry in const {
    'recipes': 'recipes',
    'foods': 'nutrition',
    'meals': 'nutrition',
    'meal-plans': 'meal_plan',
    'saved-recipes': 'saved_recipes',
    'shopping-lists': 'shopping',
    'health-videos': 'shorts',
    'welfare': 'welfare',
    'saved-welfare': 'welfare',
    'community': 'community',
    'life-guides': 'guides',
    'content-topic-requests': 'guides',
    'meal-facilities': 'assistant',
  }.entries) {
    if (p == '/api/v1/${entry.key}' || p.startsWith('/api/v1/${entry.key}/')) {
      return (
        entry.value,
        method == 'DELETE'
            ? 'delete'
            : write
            ? (entry.key == 'meals' ? 'record' : 'save')
            : 'view',
      );
    }
  }
  return null; // Excludes auth, profiles, analytics, unknown routes and all credentials.
}
