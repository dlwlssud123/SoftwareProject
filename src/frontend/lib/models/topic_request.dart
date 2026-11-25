Map<String, dynamic> topicMap(Object? value) {
  if (value is! Map<String, dynamic>) {
    throw const FormatException('Invalid topic response');
  }
  return value;
}

String _text(Object? value, {int maximum = 3000}) {
  if (value is! String ||
      value.trim().isEmpty ||
      value.runes.length > maximum) {
    throw const FormatException('Invalid text');
  }
  return value;
}

String topicUuid(Object? value, {bool submission = false}) {
  final text = _text(value, maximum: 36);
  final expression = submission
      ? r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
      : r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
  if (!RegExp(expression, caseSensitive: false).hasMatch(text)) {
    throw const FormatException('Invalid identifier');
  }
  return text;
}

DateTime _instant(Object? value) {
  final text = _text(value, maximum: 64);
  if (!RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(text)) {
    throw const FormatException('Missing timezone');
  }
  return DateTime.parse(text).toUtc();
}

enum TopicKind {
  lifeGuide('life_guide', '생활 안내'),
  video('video', '영상');

  const TopicKind(this.value, this.label);
  final String value, label;
  static TopicKind parse(Object? value) => values.firstWhere(
    (kind) => kind.value == value,
    orElse: () => throw const FormatException('Invalid kind'),
  );
}

const topicStatusLabels = {
  'received': '접수했어요',
  'reviewing': '검토하고 있어요',
  'completed': '답변이 왔어요',
  'declined': '보류 안내가 왔어요',
  'withdrawn': '취소했어요',
};

class GuideSummary {
  const GuideSummary(
    this.id,
    this.slug,
    this.title,
    this.source,
    this.checkedOn,
  );
  final String id, slug, title, source, checkedOn;
  factory GuideSummary.fromJson(Map<String, dynamic> row) {
    final slug = _text(row['slug'], maximum: 128);
    final checked = _text(row['checked_on'], maximum: 10);
    if (!RegExp(r'^[a-z0-9]+(?:-[a-z0-9]+)*$').hasMatch(slug) ||
        !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(checked) ||
        DateTime.parse(checked).toIso8601String().substring(0, 10) != checked) {
      throw const FormatException('Invalid guide source');
    }
    return GuideSummary(
      topicUuid(row['id']),
      slug,
      _text(row['title'], maximum: 200),
      _text(row['source_reference'], maximum: 1000),
      checked,
    );
  }
}

class GuideContent {
  const GuideContent(this.summary, this.steps);
  final GuideSummary summary;
  final List<({String? title, String text})> steps;
  factory GuideContent.fromJson(Map<String, dynamic> row) {
    final steps = row['steps'];
    if (steps is! List || steps.isEmpty || steps.length > 30) {
      throw const FormatException('Invalid guide steps');
    }
    return GuideContent(
      GuideSummary.fromJson(row),
      List.unmodifiable(
        steps.map((item) {
          final step = topicMap(item);
          return (
            title: step['title'] == null
                ? null
                : _text(step['title'], maximum: 120),
            text: _text(step['text']),
          );
        }),
      ),
    );
  }
}

class TopicRecord {
  const TopicRecord({
    required this.id,
    required this.kind,
    required this.status,
    required this.version,
    required this.createdAt,
    required this.updatedAt,
    this.topic,
    this.reply,
    this.guide,
  });
  final String id, status;
  final TopicKind kind;
  final int version;
  final String? topic, reply;
  final GuideSummary? guide;
  final DateTime createdAt, updatedAt;
  bool get withdrawn => status == 'withdrawn';
  factory TopicRecord.fromJson(Map<String, dynamic> row) {
    final kind = TopicKind.parse(row['kind']);
    final status = row['status'];
    final version = row['version'];
    if (!topicStatusLabels.containsKey(status) ||
        version is! int ||
        version < 1) {
      throw const FormatException('Invalid topic state');
    }
    final topic = row['topic'] == null
        ? null
        : _text(row['topic'], maximum: 60);
    final reply = row['reply'] == null
        ? null
        : _text(row['reply'], maximum: 1000);
    final guide = row['guide'] == null
        ? null
        : GuideSummary.fromJson(topicMap(row['guide']));
    if ((status == 'withdrawn' &&
            (topic != null || reply != null || guide != null)) ||
        (status != 'withdrawn' && topic == null) ||
        ({'completed', 'declined'}.contains(status) && reply == null) ||
        (guide != null &&
            (kind != TopicKind.lifeGuide || status != 'completed'))) {
      throw const FormatException('Inconsistent topic state');
    }
    return TopicRecord(
      id: topicUuid(row['id']),
      kind: kind,
      status: status as String,
      version: version,
      topic: topic,
      reply: reply,
      guide: guide,
      createdAt: _instant(row['created_at']),
      updatedAt: _instant(row['updated_at']),
    );
  }
}

class TopicPage<T> {
  const TopicPage(this.items, this.total, this.offset, this.limit);
  final List<T> items;
  final int total, offset, limit;
  factory TopicPage.fromJson(
    Map<String, dynamic> row,
    T Function(Map<String, dynamic>) parse,
  ) {
    final items = row['items'],
        total = row['total'],
        offset = row['offset'],
        limit = row['limit'];
    if (items is! List ||
        total is! int ||
        total < 0 ||
        offset is! int ||
        offset < 0 ||
        limit is! int ||
        limit < 1 ||
        limit > 100 ||
        items.length > limit) {
      throw const FormatException('Invalid page');
    }
    return TopicPage(
      List.unmodifiable(items.map((item) => parse(topicMap(item)))),
      total,
      offset,
      limit,
    );
  }
}

class PendingTopic {
  const PendingTopic(this.owner, this.submissionId, this.kind, this.topic);
  final String owner, submissionId, topic;
  final TopicKind kind;
  Map<String, dynamic> get body => {
    'submission_id': submissionId,
    'kind': kind.value,
    'topic': topic,
  };
  Map<String, dynamic> toStorage() => {...body, 'owner': owner};
  factory PendingTopic.fromStorage(Map<String, dynamic> row) {
    final topic = _text(row['topic'], maximum: 60);
    if (topic != topic.trim() || topic.contains(RegExp(r'[\x00-\x1f\x7f]'))) {
      throw const FormatException('Invalid stored topic');
    }
    return PendingTopic(
      _text(row['owner'], maximum: 128),
      topicUuid(row['submission_id'], submission: true),
      TopicKind.parse(row['kind']),
      topic,
    );
  }
}
