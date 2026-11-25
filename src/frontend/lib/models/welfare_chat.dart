import 'intake.dart';

class WelfareChatSource {
  WelfareChatSource.fromJson(Map<String, dynamic> row)
    : number = row['number'] as int,
      title = row['title'] as String,
      excerpt = row['excerpt'] as String,
      url = row['url'] == null ? null : Uri.tryParse(row['url'] as String),
      checkedAt = row['checked_at'] == null
          ? null
          : DateTime.parse(row['checked_at'] as String) {
    if (number < 1 ||
        number > 5 ||
        title.isEmpty ||
        title.length > 1000 ||
        excerpt.length > 1200) {
      throw const FormatException('Invalid welfare source');
    }
    if (row['url'] != null &&
        (url == null ||
            url!.scheme != 'https' ||
            url!.userInfo.isNotEmpty ||
            url!.port != 443 ||
            !(url!.host.endsWith('.go.kr') ||
                url!.host == 'bokjiro.go.kr' ||
                url!.host.endsWith('.bokjiro.go.kr')))) {
      throw const FormatException('Invalid official source URL');
    }
  }
  final int number;
  final String title, excerpt;
  final Uri? url;
  final DateTime? checkedAt;
}

class WelfareChatAnswer {
  WelfareChatAnswer.fromJson(Map<String, dynamic> row)
    : answer = row['answer'] as String,
      notice = row['notice'] as String,
      status = row['answer_status'] as String,
      evidence = row['evidence_status'] as String,
      region = row['region'] as String?,
      district = row['district'] as String?,
      notes = List<String>.from(row['notes'] as List),
      sources = [
        for (final source in row['sources'] as List)
          WelfareChatSource.fromJson(intakeMap(source)),
      ] {
    if (answer.isEmpty ||
        answer.length > 4000 ||
        sources.length > 5 ||
        !{'generated', 'references_only', 'no_evidence'}.contains(status) ||
        !{'ok', 'weak', 'none'}.contains(evidence) ||
        sources.map((s) => s.number).toSet().length != sources.length ||
        (status == 'generated' && sources.isEmpty) ||
        (status == 'no_evidence' && sources.isNotEmpty)) {
      throw const FormatException('Invalid welfare answer');
    }
  }
  final String answer, notice, status, evidence;
  final String? region, district;
  final List<String> notes;
  final List<WelfareChatSource> sources;
}
