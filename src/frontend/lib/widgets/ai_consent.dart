import 'package:flutter/material.dart';

Future<bool> confirmAiProcessing(
  BuildContext context, {
  required bool photo,
}) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(photo ? '음식 사진을 AI로 확인할까요?' : 'AI 도우미를 이용할까요?'),
        content: Text(
          photo
              ? '음식 사진을 NVIDIA AI 서비스로 보내 음식 이름을 찾아요. 얼굴·이름·주소·진료 정보가 없는 음식 사진만 선택해 주세요. 사진의 위치 정보는 전송 전에 제거해요. 사진은 우리 서버에 저장하지 않아요.'
              : '질문을 NVIDIA AI 서비스로 보내 답변을 받아요. 이름·연락처·주소·개인 건강기록은 적지 마세요. 질문과 답변은 우리 서버에 저장하지 않아요. 생활·요리 참고용이며 진료를 대신하지 않아요.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('동의하고 이용'),
          ),
        ],
      ),
    ) ??
    false;
