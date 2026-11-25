import 'topic_request.dart' show topicMap;

enum VideoTopic {
  stretching('stretching', '스트레칭'),
  hands('hands', '손 운동'),
  healthyLife('healthy_life', '건강생활');

  const VideoTopic(this.value, this.label);
  final String value, label;
  static VideoTopic parse(Object? value) => values.firstWhere(
    (item) => item.value == value,
    orElse: () => throw const FormatException('Invalid video topic'),
  );
}

String _text(Object? value, int max) {
  if (value is! String || value.trim().isEmpty || value.runes.length > max) {
    throw const FormatException('Invalid video text');
  }
  return value;
}

class HealthVideo {
  const HealthVideo(
    this.id,
    this.topic,
    this.title,
    this.publisher,
    this.videoId,
    this.sourceUrl,
    this.checkedOn,
  );
  final String id, title, publisher, videoId, checkedOn;
  final VideoTopic topic;
  final Uri sourceUrl;
  Uri get watchUrl => Uri.https('www.youtube.com', '/watch', {'v': videoId});
  factory HealthVideo.fromJson(Map<String, dynamic> row) {
    final id = _text(row['id'], 60),
        videoId = _text(row['video_id'], 11),
        checked = _text(row['checked_on'], 10);
    final source = Uri.parse(_text(row['source_url'], 1000));
    if (!RegExp(r'^[a-z0-9]+(?:-[a-z0-9]+)*$').hasMatch(id) ||
        !RegExp(r'^[A-Za-z0-9_-]{11}$').hasMatch(videoId) ||
        !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(checked) ||
        DateTime.parse(checked).toIso8601String().substring(0, 10) != checked ||
        source.scheme != 'https' ||
        source.userInfo.isNotEmpty ||
        source.hasFragment ||
        (source.hasPort && source.port != 443) ||
        !const {'www.seohae.go.kr', 'www.youtube.com'}.contains(source.host)) {
      throw const FormatException('Invalid video link');
    }
    return HealthVideo(
      id,
      VideoTopic.parse(row['topic']),
      _text(row['title'], 120),
      _text(row['publisher'], 100),
      videoId,
      source,
      checked,
    );
  }
}

class HealthVideoPage {
  const HealthVideoPage(this.items, this.total, this.offset, this.limit);
  final List<HealthVideo> items;
  final int total, offset, limit;
  bool get hasNext => offset + items.length < total;
  factory HealthVideoPage.fromJson(Map<String, dynamic> row) {
    if (row['items'] is! List ||
        row['total'] is! int ||
        row['offset'] is! int ||
        row['limit'] is! int ||
        (row['total'] as int) < 0 ||
        (row['offset'] as int) < 0 ||
        (row['limit'] as int) < 1 ||
        (row['items'] as List).length > (row['limit'] as int)) {
      throw const FormatException('Invalid video page');
    }
    return HealthVideoPage(
      List.unmodifiable(
        (row['items'] as List).map(
          (item) => HealthVideo.fromJson(topicMap(item)),
        ),
      ),
      row['total'] as int,
      row['offset'] as int,
      row['limit'] as int,
    );
  }
}
