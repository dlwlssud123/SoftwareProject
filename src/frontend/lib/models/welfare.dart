class WelfareService {
  WelfareService.fromJson(Map<String, dynamic> json)
    : id = json['service_id'] as String,
      title = json['title'] as String,
      summary = json['summary'] as String,
      target = json['target_text'] as String,
      selection = json['selection_text'] as String,
      benefit = json['benefit_text'] as String,
      region = [json['ctpv'], json['sgg']].whereType<String>().join(' '),
      applications = [
        for (final item in json['application'] as List)
          '${item['method']}\n${item['description']}',
      ],
      contacts = [
        for (final item in json['contacts'] as List)
          '${item['name']} ${item['contact']}',
      ],
      flagged = json['quality_status'] != 'ok',
      sourceUrl = json['source']['source_url'] as String,
      checkedAt = DateTime.parse(
        (json['source']['detail_checked_at'] ?? json['source']['checked_at'])
            as String,
      );

  final String id,
      title,
      summary,
      target,
      selection,
      benefit,
      region,
      sourceUrl;
  final List<String> applications, contacts;
  final bool flagged;
  final DateTime checkedAt;

  // Only official HTTPS sources can be opened; displayed text never executes HTML.
  Uri? get officialUrl {
    final uri = Uri.tryParse(sourceUrl);
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.userInfo.isNotEmpty ||
        uri.port != 443 ||
        !uri.host.endsWith('.go.kr')) {
      return null;
    }
    return uri;
  }
}

class WelfareMatch {
  WelfareMatch.fromJson(Map<String, dynamic> json)
    : service = WelfareService.fromJson(json['item'] as Map<String, dynamic>),
      reasons = List<String>.from(json['reasons'] as List);
  final WelfareService service;
  final List<String> reasons;
}

class WelfareResults {
  WelfareResults.fromJson(Map<String, dynamic> json)
    : items = [
        for (final row in json['items'] as List)
          WelfareMatch.fromJson(row as Map<String, dynamic>),
      ],
      warnings = List<String>.from(json['warnings'] as List);
  final List<WelfareMatch> items;
  final List<String> warnings;
}

class SavedWelfare {
  SavedWelfare.fromJson(Map<String, dynamic> json)
    : id = json['service_id'] as String,
      title = json['title'] as String?;
  final String id;
  final String? title;
}

class SavedWelfarePage {
  SavedWelfarePage.fromJson(Map<String, dynamic> json)
    : items = [
        for (final row in json['items'] as List)
          SavedWelfare.fromJson(row as Map<String, dynamic>),
      ],
      total = json['total'] as int;
  final List<SavedWelfare> items;
  final int total;
}

class WelfareNote {
  WelfareNote.fromJson(Map<String, dynamic> json)
    : text = json['note'] as String?,
      updatedAt = json['updated_at'] == null
          ? null
          : DateTime.parse(json['updated_at'] as String);
  final String? text;
  final DateTime? updatedAt;
}

String welfareDate(DateTime instant) {
  final time = instant.toUtc().add(const Duration(hours: 9));
  return '${time.year}.${time.month.toString().padLeft(2, '0')}.'
      '${time.day.toString().padLeft(2, '0')} (한국 시간)';
}
