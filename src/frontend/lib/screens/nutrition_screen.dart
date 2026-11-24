import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../data/demo_repository.dart';
import '../models/recommendations.dart' show nutrientLabel;
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../data/intake_api.dart';
import '../models/intake.dart';
import 'intake_screens.dart';
import '../data/ai_api.dart';
import '../core/network/api_exception.dart';
import '../widgets/ai_consent.dart';
import 'photo_food_screen.dart';

class NutritionScreen extends StatefulWidget {
  const NutritionScreen({
    required this.repository,
    required this.settings,
    this.document = false,
    this.intakeApi,
    this.aiApi,
    super.key,
  });
  final DemoRepository repository;
  final AppSettings settings;
  final bool document;
  final IntakeApi? intakeApi;
  final AiApi? aiApi;
  @override
  State<NutritionScreen> createState() => _NutritionScreenState();
}

class _NutritionScreenState extends State<NutritionScreen> {
  XFile? photo;
  bool example = false, analyzed = false, picking = false;
  bool _analyzing = false, _consented = false;
  String? _aiError;
  CancelToken? _request;

  Future<void> _analyze() async {
    if (_analyzing ||
        photo == null ||
        widget.aiApi == null ||
        widget.intakeApi == null) {
      return;
    }
    setState(() {
      _analyzing = true;
      _aiError = null;
    });
    try {
      if (!_consented) {
        final allowed = await confirmAiProcessing(context, photo: true);
        if (!allowed || !mounted) return;
        _consented = true;
      }
      final chosen = photo!;
      if (await chosen.length() > 2 * 1024 * 1024) {
        throw const ApiException(
          ApiErrorType.badResponse,
          '2MB 이하의 음식 사진을 골라 주세요.',
        );
      }
      final bytes = await chosen.readAsBytes();
      if (!mounted) return;
      _request = CancelToken();
      final result = await widget.aiApi!.photo(bytes, _request!);
      if (!mounted) return;
      final saved = await Navigator.of(context).push<SavedIntake>(
        MaterialPageRoute(
          builder: (_) =>
              PhotoFoodScreen(result: result, api: widget.intakeApi!),
        ),
      );
      if (saved != null && mounted) showMessage(context, '식사를 저장했어요.');
    } on ApiException catch (error) {
      if (mounted) setState(() => _aiError = error.message);
    } on Exception {
      if (mounted) setState(() => _aiError = '사진을 읽지 못했어요. 다시 선택해 주세요.');
    } finally {
      if (mounted) setState(() => _analyzing = false);
    }
  }

  @override
  void dispose() {
    _request?.cancel();
    super.dispose();
  }

  Future<void> _record(IntakeApi api) async {
    final saved = await Navigator.of(context).push<SavedIntake>(
      MaterialPageRoute(builder: (_) => IntakeEditor(api: api)),
    );
    if (saved == null || !mounted) return;
    showMessage(context, '식사를 저장했어요.');
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => IntakeDetailScreen(api: api, id: saved.id),
      ),
    );
  }

  Future<void> pick(ImageSource source) async {
    if (picking || _analyzing) return;
    setState(() => picking = true);
    try {
      final image = await ImagePicker().pickImage(
        source: source,
        maxWidth: 1024,
        maxHeight: 1024,
        imageQuality: 80,
      );
      if (mounted && image != null) {
        setState(() {
          photo = image;
          example = false;
          analyzed = false;
          _aiError = null;
        });
      }
    } catch (_) {
      if (mounted) {
        showMessage(context, '사진을 열 수 없어요. 기기의 카메라와 사진 접근 상태를 확인해 주세요.');
      }
    } finally {
      if (mounted) setState(() => picking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    const previewHeight = 180.0;
    final cacheHeight = (previewHeight * MediaQuery.devicePixelRatioOf(context))
        .ceil();
    final recipe = widget.repository.recipes.first;
    final hasPhoto = photo != null || example;
    final content = ListView(
      padding: const EdgeInsets.fromLTRB(16, 20, 16, 24),
      children: [
        if (!widget.document && widget.intakeApi != null) ...[
          const SectionTitle('음식과 양으로 영양 확인'),
          FeatureTile(
            key: const Key('intake-start'),
            title: '먹은 음식 직접 입력',
            subtitle: '음식과 먹은 양을 골라 실제 식사를 기록해요',
            icon: Icons.restaurant_outlined,
            onTap: () => _record(widget.intakeApi!),
          ),
          FeatureTile(
            key: const Key('intake-history'),
            title: '저장한 식사',
            subtitle: '음식·양·시간 확인과 수정·삭제',
            icon: Icons.receipt_long_outlined,
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => IntakeHistoryScreen(api: widget.intakeApi!),
              ),
            ),
          ),
          SectionTitle(widget.aiApi == null ? '사진 기능 체험' : '음식 사진으로 간편 입력'),
        ],
        if (hasPhoto)
          Container(
            height: previewHeight,
            decoration: BoxDecoration(
              border: Border.all(color: line),
              borderRadius: BorderRadius.circular(10),
            ),
            clipBehavior: Clip.antiAlias,
            child: photo != null
                ? Image.file(
                    File(photo!.path),
                    fit: BoxFit.contain,
                    cacheHeight: cacheHeight,
                    errorBuilder: (_, _, _) =>
                        const Center(child: Text('사진을 다시 선택해 주세요.')),
                  )
                : Image.asset(
                    recipe.image,
                    fit: BoxFit.contain,
                    cacheHeight: cacheHeight,
                  ),
          )
        else
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 18),
            child: Center(
              child: Container(
                width: 88,
                height: 88,
                decoration: BoxDecoration(
                  color: const Color(0xFFE9F3FF),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: const Icon(
                  Icons.document_scanner_outlined,
                  color: blue,
                  size: 48,
                ),
              ),
            ),
          ),
        const SizedBox(height: 18),
        Text(
          widget.document ? '사진 속 내용을 살펴보세요' : '식사 사진으로 영양을 확인하세요',
          textAlign: TextAlign.center,
          style: const TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            height: 1.5,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          widget.document ? '안내문이나 약 봉투 사진을 선택해 주세요.' : '사진을 찍거나 앨범에서 선택해 주세요.',
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 16, color: muted, height: 1.5),
        ),
        const SizedBox(height: 18),
        Notice(
          !widget.document && widget.aiApi != null
              ? '사진에서 음식을 찾고 예상 1인분으로 영양을 확인해요. 음식과 양을 직접 바꿀 수 있어요.'
              : '사진 선택과 예시 결과를 체험할 수 있어요. 이 화면의 AI 분석은 연결되지 않았어요.',
          color: Color(0xFF875200),
        ),
        const SizedBox(height: 22),
        FilledButton.icon(
          onPressed: picking || _analyzing
              ? null
              : () => pick(ImageSource.camera),
          icon: const Icon(Icons.camera_alt_rounded),
          label: const Text('사진 촬영하기'),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xFF248A45),
          ),
          onPressed: picking || _analyzing
              ? null
              : () => pick(ImageSource.gallery),
          icon: const Icon(Icons.photo_library_rounded),
          label: const Text('앨범에서 선택하기'),
        ),
        if (!widget.document &&
            widget.aiApi != null &&
            widget.intakeApi != null &&
            photo != null) ...[
          const SizedBox(height: 12),
          FilledButton.icon(
            key: const Key('photo-analyze'),
            onPressed: _analyzing ? null : _analyze,
            icon: const Icon(Icons.auto_awesome),
            label: Text(_analyzing ? '음식을 찾고 있어요…' : '음식 찾고 영양 확인'),
          ),
          if (_analyzing) const LinearProgressIndicator(),
          if (_aiError != null) Notice('$_aiError\n직접 입력도 이용할 수 있어요.'),
        ],
        if (!widget.document && widget.aiApi == null) ...[
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: () => setState(() {
              photo = null;
              example = true;
              analyzed = true;
            }),
            icon: const Icon(Icons.science_outlined),
            label: const Text('예시 영양 결과 보기'),
          ),
        ],
        if (analyzed && !widget.document) ...[
          const SectionTitle('예시 영양 정보', trailing: Tag('공개 레시피')),
          Text(recipe.name, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            decoration: BoxDecoration(
              border: Border.all(color: line),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Column(
              children: [
                for (final entry in {
                  '열량': nutrientLabel(recipe.calories, 'kcal'),
                  '탄수화물': nutrientLabel(recipe.carbs, 'g'),
                  '단백질': nutrientLabel(recipe.protein, 'g'),
                  '지방': nutrientLabel(recipe.fat, 'g'),
                  '나트륨': nutrientLabel(recipe.sodium, 'mg'),
                }.entries)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    child: Row(
                      children: [
                        Text(entry.key, style: const TextStyle(fontSize: 17)),
                        const Spacer(),
                        Text(
                          entry.value,
                          style: const TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            '식품안전나라 제공 수치이며 실제 섭취량에 따라 달라져요. 선택한 사진의 분석 결과는 아니에요.',
            style: TextStyle(fontSize: 14, color: muted, height: 1.5),
          ),
        ],
        const SizedBox(height: 20),
        Text(
          !widget.document && widget.aiApi != null
              ? '음식 찾기를 누르면 사진이 서버와 NVIDIA로 전송돼요. 분석 후 우리 서버에는 사진을 보관하지 않아요.'
              : '사진을 별도로 보관하거나 서버로 전송하지 않아요.',
          style: TextStyle(fontSize: 14, color: muted, height: 1.5),
        ),
      ],
    );
    return widget.document
        ? Scaffold(
            appBar: AppBar(title: const Text('사진 도우미')),
            body: content,
          )
        : content;
  }
}
