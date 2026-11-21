final facilityIdPattern = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
);

class MealFacility {
  MealFacility.fromJson(Map<String, dynamic> json)
    : id = json['id'] as String,
      name = json['name'] as String,
      region = '${json['sido'] as String} ${json['sigungu'] as String}'.trim(),
      address = json['address'] as String?,
      eligibility = json['eligibility_text'] as String?,
      hours = json['hours_text'] as String?,
      contact = json['contact_text'] as String?,
      sourceUrl = json['source_url'] as String,
      provider = json['provider'] as String?,
      checkedOn = DateTime.parse(json['checked_on'] as String),
      referenceDate = json['reference_date'] == null
          ? null
          : DateTime.parse(json['reference_date'] as String),
      cautions = List<String>.from(json['cautions'] as List),
      qualityFlags = List<String>.from(json['quality_flags'] as List),
      distanceKm = (json['distance_km'] as num?)?.toDouble() {
    if (!facilityIdPattern.hasMatch(id) ||
        name.trim().isEmpty ||
        (distanceKm != null && (!distanceKm!.isFinite || distanceKm! < 0))) {
      throw const FormatException('Invalid facility');
    }
  }

  final String id, name, region, sourceUrl;
  final String? address, eligibility, hours, contact, provider;
  final DateTime checkedOn;
  final DateTime? referenceDate;
  final List<String> cautions, qualityFlags;
  final double? distanceKm;

  Uri? get officialUrl {
    final uri = Uri.tryParse(sourceUrl);
    return uri != null &&
            uri.scheme == 'https' &&
            uri.port == 443 &&
            uri.userInfo.isEmpty &&
            uri.host.endsWith('.go.kr')
        ? uri
        : null;
  }

  Uri? get mapUrl => address == null || address!.trim().isEmpty
      ? null
      : Uri.https('map.naver.com', '/p/search/${address!.trim()}');

  // Only a single ordinary telephone number can open the dialer, never USSD.
  Uri? get phoneUrl {
    final phone = contact?.replaceAll(RegExp(r'[\s()\-]'), '');
    return phone != null && RegExp(r'^0[0-9]{8,10}$').hasMatch(phone)
        ? Uri(scheme: 'tel', path: phone)
        : null;
  }
}

class FacilityPage {
  FacilityPage.fromJson(Map<String, dynamic> json)
    : items = [
        for (final row in json['items'] as List)
          MealFacility.fromJson(row as Map<String, dynamic>),
      ],
      total = json['total'] as int,
      offset = json['offset'] as int,
      warnings = List<String>.from(json['warnings'] as List) {
    if (total < 0 ||
        offset < 0 ||
        (items.isNotEmpty && offset + items.length > total)) {
      throw const FormatException('Invalid facility page');
    }
  }
  final List<MealFacility> items;
  final List<String> warnings;
  final int total, offset;
}

String facilityDate(DateTime date) => '${date.year}.${date.month}.${date.day}';
