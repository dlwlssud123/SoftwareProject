import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../data/demo_repository.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/common.dart';

class NutritionScreen extends StatefulWidget {
  const NutritionScreen({
    required this.repository,
    required this.settings,
    this.document = false,
    super.key,
  });
  final DemoRepository repository;
  final AppSettings settings;
  final bool document;
  @override
  State<NutritionScreen> createState() => _NutritionScreenState();
}

class _NutritionScreenState extends State<NutritionScreen> {
  XFile? photo;
  bool example = false, analyzed = false, picking = false;

  Future<void> pick(ImageSource source) async {
    if (picking) return;
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
    final recipe = widget.repository.recipes.first;
    final hasPhoto = photo != null || example;
    final content = ListView(
      padding: const EdgeInsets.fromLTRB(16, 20, 16, 24),
      children: [
        if (hasPhoto)
          Container(
            height: 180,
            decoration: BoxDecoration(
              border: Border.all(color: line),
              borderRadius: BorderRadius.circular(10),
            ),
            clipBehavior: Clip.antiAlias,
            child: photo != null
                ? Image.file(
                    File(photo!.path),
                    fit: BoxFit.contain,
                    errorBuilder: (_, _, _) =>
                        const Center(child: Text('사진을 다시 선택해 주세요.')),
                  )
                : Image.asset(recipe.image, fit: BoxFit.contain),
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
        const Notice(
          '사진 선택과 예시 결과를 체험할 수 있어요. 직접 고른 사진의 AI 분석은 아직 연결되지 않았어요.',
          color: Color(0xFF875200),
        ),
        const SizedBox(height: 22),
        FilledButton.icon(
          onPressed: picking ? null : () => pick(ImageSource.camera),
          icon: const Icon(Icons.camera_alt_rounded),
          label: const Text('사진 촬영하기'),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xFF248A45),
          ),
          onPressed: picking ? null : () => pick(ImageSource.gallery),
          icon: const Icon(Icons.photo_library_rounded),
          label: const Text('앨범에서 선택하기'),
        ),
        if (!widget.document) ...[
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
                  '열량': '${recipe.calories.toStringAsFixed(0)} kcal',
                  '탄수화물': '${recipe.carbs.toStringAsFixed(0)} g',
                  '단백질': '${recipe.protein.toStringAsFixed(0)} g',
                  '지방': '${recipe.fat.toStringAsFixed(0)} g',
                  '나트륨': '${recipe.sodium.toStringAsFixed(0)} mg',
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
        const Text(
          '사진을 별도로 보관하거나 서버로 전송하지 않아요.',
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
