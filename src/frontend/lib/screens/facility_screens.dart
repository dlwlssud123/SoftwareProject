import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import '../core/network/api_exception.dart';
import '../data/facility_api.dart';
import '../models/facility.dart';
import '../services/facility_location.dart';
import '../widgets/common.dart';

class FacilitySearchScreen extends StatefulWidget {
  const FacilitySearchScreen({
    required this.api,
    this.locationFactory,
    super.key,
  });
  final FacilityApi api;
  final FacilityLocationLookup Function()? locationFactory;
  @override
  State<FacilitySearchScreen> createState() => _FacilitySearchScreenState();
}

class _FacilitySearchScreenState extends State<FacilitySearchScreen>
    with WidgetsBindingObserver {
  final _district = TextEditingController(), _query = TextEditingController();
  String? _region, _error, _locationNotice;
  double _radius = 5;
  Position? _position;
  FacilityLocationLookup? _lookup;
  CancelToken? _request;
  FacilityPage? _page;
  final List<MealFacility> _items = [];
  bool _busy = false, _nearby = false;
  int _generation = 0;
  static const _regions = [
    '서울특별시',
    '부산광역시',
    '대구광역시',
    '인천광역시',
    '광주광역시',
    '대전광역시',
    '울산광역시',
    '세종특별자치시',
    '경기도',
    '강원특별자치도',
    '충청북도',
    '충청남도',
    '전북특별자치도',
    '전라남도',
    '경상북도',
    '경상남도',
    '제주특별자치도',
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  void _cancel() {
    _generation++;
    _lookup?.cancel();
    _lookup = null;
    _request?.cancel();
    _request = null;
    _busy = false;
  }

  void _reset() {
    _cancel();
    _position = null;
    _page = null;
    _items.clear();
    _error = null;
    _locationNotice = null;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!TickerMode.valuesOf(context).enabled) _reset();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // The native permission dialog may make the app inactive temporarily.
    if (state != AppLifecycleState.paused &&
            state != AppLifecycleState.hidden &&
            state != AppLifecycleState.detached ||
        !mounted) {
      return;
    }
    setState(_reset);
  }

  @override
  void dispose() {
    _cancel();
    _position = null;
    WidgetsBinding.instance.removeObserver(this);
    _district.dispose();
    _query.dispose();
    super.dispose();
  }

  Future<void> _search({required bool nearby, bool more = false}) async {
    if (_busy) return;
    if (!nearby && _region == null) {
      setState(() => _error = '찾으실 시·도를 선택해 주세요.');
      return;
    }
    FocusScope.of(context).unfocus();
    if (!more) _reset();
    final generation = ++_generation;
    setState(() {
      _busy = true;
      _error = null;
      _nearby = nearby;
    });
    try {
      if (nearby && !more) {
        _lookup = widget.locationFactory?.call() ?? FacilityLocationLookup();
        final point = await _lookup!.start();
        if (!mounted || generation != _generation) return;
        _position = point;
        _locationNotice = '위치 오차 약 ${point.accuracy.ceil()}m · 직선거리 기준이에요.';
      }
      if (!mounted || generation != _generation) return;
      final token = _request = CancelToken();
      final offset = more ? _items.length : 0;
      final page = nearby
          ? await widget.api.nearby(
              latitude: _position!.latitude,
              longitude: _position!.longitude,
              radiusKm: _radius,
              region: _region,
              district: _district.text.trim(),
              query: _query.text.trim(),
              offset: offset,
              cancelToken: token,
            )
          : await widget.api.search(
              region: _region!,
              district: _district.text.trim(),
              query: _query.text.trim(),
              offset: offset,
              cancelToken: token,
            );
      if (!mounted || generation != _generation) return;
      setState(() {
        _page = page;
        _items.addAll(page.items);
      });
    } on FacilityLocationException catch (error) {
      if (mounted && generation == _generation && !error.cancelled) {
        setState(() {
          _position = null;
          _error = error.message;
        });
      }
    } on ApiException catch (error) {
      if (mounted && generation == _generation) {
        setState(() => _error = error.message);
      }
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('무료급식소 · 경로식당')),
    body: ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 100),
      children: [
        const Notice('이용 대상·식사 시간은 시설마다 달라요. 방문 전에 전화로 확인해 주세요.'),
        const SectionTitle('내 주변에서 찾기'),
        const Text(
          '버튼을 누르면 위치 권한을 요청해요. 위치는 이번 검색을 위해 서버에 보내며 저장하지 않아요. 허용하지 않아도 아래에서 지역으로 찾을 수 있어요.',
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<double>(
          initialValue: _radius,
          isExpanded: true,
          decoration: const InputDecoration(labelText: '찾을 거리'),
          items: [
            for (final radius in [1.0, 5.0, 10.0])
              DropdownMenuItem(
                value: radius,
                child: Text('반경 ${radius.toInt()}km'),
              ),
          ],
          onChanged: _busy
              ? null
              : (value) => setState(() {
                  _reset();
                  _radius = value!;
                }),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          key: const Key('facility-nearby'),
          onPressed: _busy ? null : () => _search(nearby: true),
          icon: const Icon(Icons.my_location),
          label: const Text('내 주변 급식소 찾기'),
        ),
        const SectionTitle('지역으로 찾기'),
        DropdownButtonFormField<String>(
          key: const Key('facility-region'),
          initialValue: _region,
          isExpanded: true,
          decoration: const InputDecoration(labelText: '시·도 선택'),
          items: [
            for (final region in _regions)
              DropdownMenuItem(value: region, child: Text(region)),
          ],
          onChanged: _busy
              ? null
              : (value) => setState(() {
                  _reset();
                  _region = value;
                  _district.clear();
                }),
        ),
        const SizedBox(height: 16),
        TextField(
          key: const Key('facility-district'),
          controller: _district,
          enabled: !_busy,
          maxLength: 50,
          decoration: const InputDecoration(
            labelText: '시·군·구 (선택)',
            hintText: '예: 남구',
          ),
          onChanged: (_) => setState(_reset),
        ),
        TextField(
          key: const Key('facility-query'),
          controller: _query,
          enabled: !_busy,
          maxLength: 100,
          decoration: const InputDecoration(labelText: '시설명·주소 (선택)'),
          onChanged: (_) => setState(_reset),
        ),
        OutlinedButton.icon(
          key: const Key('facility-find-region'),
          onPressed: _busy ? null : () => _search(nearby: false),
          icon: const Icon(Icons.search),
          label: const Text('선택한 지역에서 찾기'),
        ),
        if (_busy) ...[
          const LinearProgressIndicator(),
          const Text('찾고 있어요. 잠시만 기다려 주세요.'),
          TextButton(
            onPressed: () => setState(_reset),
            child: const Text('찾기 취소'),
          ),
        ],
        if (_error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Notice(_error!),
          ),
        if (_page != null) ...[
          SectionTitle('찾은 급식소 ${_page!.total}곳'),
          if (_locationNotice != null) Text(_locationNotice!),
          for (final warning in _page!.warnings) Notice(warning),
          if (_items.isEmpty)
            const Notice('등록된 급식소를 찾지 못했어요. 검색어나 시·군·구를 비우거나 다른 지역으로 찾아보세요.'),
          for (final item in _items)
            Card(
              child: ListTile(
                contentPadding: const EdgeInsets.all(16),
                title: Text(item.name),
                subtitle: Text(
                  '${_nearby
                      ? item.distanceKm == null
                            ? '거리 확인 불가\n'
                            : '직선 약 ${item.distanceKm!.toStringAsFixed(1)}km\n'
                      : ''}${item.address ?? item.region}',
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) =>
                        FacilityDetailScreen(api: widget.api, id: item.id),
                  ),
                ),
              ),
            ),
          if (_items.length < _page!.total && _items.length < 10000)
            OutlinedButton(
              onPressed: _busy
                  ? null
                  : () => _search(nearby: _nearby, more: true),
              child: const Text('급식소 더 보기'),
            ),
        ],
      ],
    ),
  );
}

class FacilityDetailScreen extends StatefulWidget {
  const FacilityDetailScreen({required this.api, required this.id, super.key});
  final FacilityApi api;
  final String id;
  @override
  State<FacilityDetailScreen> createState() => _FacilityDetailScreenState();
}

class _FacilityDetailScreenState extends State<FacilityDetailScreen> {
  CancelToken? _request;
  late Future<MealFacility> _detail;
  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _request?.cancel();
    _request = CancelToken();
    _detail = widget.api.detail(widget.id, cancelToken: _request);
  }

  @override
  void dispose() {
    _request?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('급식소 상세')),
    body: FutureBuilder<MealFacility>(
      future: _detail,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          final error = snapshot.error;
          final missing = error is ApiException && error.statusCode == 404;
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Notice(
                missing
                    ? '현재 공개된 안내를 찾을 수 없어요. 목록으로 돌아가 다시 찾아 주세요.'
                    : error is ApiException
                    ? error.message
                    : '안내를 확인하지 못했어요.',
              ),
              if (!missing)
                OutlinedButton(
                  onPressed: () => setState(_load),
                  child: const Text('다시 확인'),
                ),
            ],
          );
        }
        final item = snapshot.data!;
        return ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 100),
          children: [
            Text(item.name, style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 12),
            const Notice(
              '누구나 무료로 이용할 수 있다는 뜻은 아니에요. 방문 전에 대상·운영 여부·시간을 확인해 주세요.',
            ),
            for (final field in [
              ('주소', item.address ?? item.region),
              ('이용 대상', item.eligibility),
              ('식사·운영 시간', item.hours),
              ('문의 전화', item.contact),
            ]) ...[
              SectionTitle(field.$1),
              SelectableText(
                field.$2?.trim().isNotEmpty == true
                    ? field.$2!
                    : '등록된 안내가 없어요. 담당 기관에 확인해 주세요.',
              ),
            ],
            if (item.phoneUrl != null)
              OutlinedButton.icon(
                onPressed: () => openLink(context, item.phoneUrl!),
                icon: const Icon(Icons.call_outlined),
                label: const Text('전화 앱에서 문의하기'),
              ),
            if (item.mapUrl != null)
              OutlinedButton.icon(
                onPressed: () => openLink(context, item.mapUrl!),
                icon: const Icon(Icons.map_outlined),
                label: const Text('외부 지도에서 주소 보기'),
              ),
            const SectionTitle('방문 전 확인할 내용'),
            for (final caution in item.cautions) Notice(caution),
            if (item.qualityFlags.isNotEmpty)
              const Notice('일부 정보에 확인이 필요해요. 문의처와 원문 안내를 함께 확인해 주세요.'),
            const SectionTitle('정보 출처'),
            Text('확인일: ${facilityDate(item.checkedOn)}'),
            if (item.referenceDate != null)
              Text('원천 자료 기준일: ${facilityDate(item.referenceDate!)}'),
            if (item.provider != null) Text(item.provider!),
            SelectableText(item.sourceUrl),
            if (item.officialUrl != null)
              OutlinedButton.icon(
                onPressed: () => openLink(context, item.officialUrl!),
                icon: const Icon(Icons.open_in_new),
                label: const Text('공식 출처 열기'),
              ),
          ],
        );
      },
    ),
  );
}
