import 'topic_request.dart' show topicMap, topicUuid;

enum CommunityCategory {
  meal('meal', '식사 이야기'),
  daily('daily', '일상 이야기');

  const CommunityCategory(this.value, this.label);
  final String value, label;
  static CommunityCategory parse(Object? value) => values.firstWhere(
    (item) => item.value == value,
    orElse: () => throw const FormatException('Invalid community category'),
  );
}

String communityText(Object? value, int maximum) {
  if (value is! String ||
      value.trim().isEmpty ||
      value.runes.length > maximum) {
    throw const FormatException('Invalid community text');
  }
  return value;
}

DateTime _date(Object? value) {
  final text = communityText(value, 64);
  if (!RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(text)) {
    throw const FormatException('Missing timezone');
  }
  return DateTime.parse(text).toUtc();
}

class CommunityPost {
  const CommunityPost({
    required this.id,
    required this.category,
    required this.title,
    required this.body,
    required this.authorLabel,
    required this.isMine,
    required this.status,
    required this.version,
    required this.createdAt,
  });
  final String id, title, body, authorLabel, status;
  final CommunityCategory category;
  final bool isMine;
  final int version;
  final DateTime createdAt;
  factory CommunityPost.fromJson(Map<String, dynamic> row) {
    if (row['is_mine'] is! bool ||
        row['version'] is! int ||
        (row['version'] as int) < 1 ||
        !const ['published', 'hidden', 'deleted'].contains(row['status'])) {
      throw const FormatException('Invalid community post');
    }
    return CommunityPost(
      id: topicUuid(row['id']),
      category: CommunityCategory.parse(row['category']),
      title: communityText(row['title'], 60),
      body: communityText(row['body'], 2000),
      authorLabel: communityText(row['author_label'], 100),
      isMine: row['is_mine'] as bool,
      status: row['status'] as String,
      version: row['version'] as int,
      createdAt: _date(row['created_at']),
    );
  }
}

class CommunityBlock {
  const CommunityBlock(this.id, this.authorLabel);
  final String id, authorLabel;
  factory CommunityBlock.fromJson(Map<String, dynamic> row) => CommunityBlock(
    topicUuid(row['id']),
    communityText(row['author_label'], 100),
  );
}

class CommunityPage<T> {
  const CommunityPage(this.items, this.total, this.offset, this.limit);
  final List<T> items;
  final int total, offset, limit;
  bool get hasNext => offset + items.length < total;
  factory CommunityPage.fromJson(
    Map<String, dynamic> row,
    T Function(Map<String, dynamic>) parse,
  ) {
    if (row['items'] is! List ||
        row['total'] is! int ||
        row['offset'] is! int ||
        row['limit'] is! int ||
        (row['total'] as int) < 0 ||
        (row['offset'] as int) < 0 ||
        (row['limit'] as int) < 1 ||
        (row['items'] as List).length > (row['limit'] as int)) {
      throw const FormatException('Invalid community page');
    }
    return CommunityPage(
      List.unmodifiable(
        (row['items'] as List).map((item) => parse(topicMap(item))),
      ),
      row['total'] as int,
      row['offset'] as int,
      row['limit'] as int,
    );
  }
}

class PendingCommunityPost {
  const PendingCommunityPost(
    this.owner,
    this.submissionId,
    this.category,
    this.title,
    this.body,
  );
  final String owner, submissionId, title, body;
  final CommunityCategory category;
  Map<String, dynamic> get payload => {
    'submission_id': submissionId,
    'category': category.value,
    'title': title,
    'body': body,
  };
  Map<String, dynamic> get storage => {...payload, 'owner': owner};
  factory PendingCommunityPost.fromJson(Map<String, dynamic> row) =>
      PendingCommunityPost(
        communityText(row['owner'], 100),
        topicUuid(row['submission_id'], submission: true),
        CommunityCategory.parse(row['category']),
        communityText(row['title'], 60),
        communityText(row['body'], 2000),
      );
}
