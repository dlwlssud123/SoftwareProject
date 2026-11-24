import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import '../data/ai_api.dart';
import '../core/network/api_exception.dart';
import '../widgets/ai_consent.dart';
import '../data/demo_repository.dart';
import '../data/welfare_api.dart';
import '../data/topic_api.dart';
import '../data/facility_api.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'profile_form.dart';
import 'nutrition_screen.dart';
import 'welfare_screens.dart';
import 'topic_screens.dart';
import 'facility_screens.dart';

class AssistantScreen extends StatelessWidget {
  const AssistantScreen({
    required this.repository,
    required this.settings,
    this.welfareApi,
    this.topicApi,
    this.facilityApi,
    this.aiApi,
    super.key,
  });
  final DemoRepository repository;
  final AppSettings settings;
  final WelfareApi? welfareApi;
  final TopicApi? topicApi;
  final FacilityApi? facilityApi;
  final AiApi? aiApi;
  void chat(BuildContext context) => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => ConversationScreen(settings: settings, api: aiApi),
    ),
  );
  void places(BuildContext context) => showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              '어디를 찾으세요?',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 14),
            for (final place in ['약국', '병원', '주민센터'])
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: OutlinedButton.icon(
                  onPressed: () {
                    Navigator.of(ctx).pop();
                    openLink(
                      context,
                      Uri.https('map.naver.com', '/p/search/가까운 $place'),
                    );
                  },
                  icon: const Icon(Icons.place_outlined),
                  label: Text(place),
                ),
              ),
            const Text(
              '외부 지도 검색으로 연결돼요.',
              style: TextStyle(fontSize: 14, color: muted),
            ),
          ],
        ),
      ),
    ),
  );
  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(16, 10, 16, 24),
    children: [
      FeatureTile(
        title: '건강상담',
        subtitle: '건강·생활 대화 화면을 체험해 보세요',
        icon: Icons.medical_services_outlined,
        color: green,
        background: const Color(0xFFEAF5ED),
        onTap: () => chat(context),
      ),
      FeatureTile(
        title: '복지 소식 · 맞춤 추천',
        subtitle: welfareApi == null
            ? '예시로 복지 찾기 체험'
            : '내 지역의 복지 찾기 · 저장한 복지와 메모',
        icon: Icons.campaign_rounded,
        color: const Color(0xFFCE4149),
        background: const Color(0xFFFFF0F0),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => welfareApi != null
                ? WelfareSearchScreen(api: welfareApi!)
                : ProfileForm(
                    repository: repository,
                    settings: settings,
                    welfare: true,
                  ),
          ),
        ),
      ),
      FeatureTile(
        title: '무료급식소 · 경로식당',
        subtitle: facilityApi == null
            ? '서버 연결 후 이용할 수 있어요'
            : '내 주변·지역으로 찾기 · 방문 전 확인',
        icon: Icons.soup_kitchen_outlined,
        onTap: () {
          if (facilityApi == null) {
            showMessage(context, '급식소 검색은 서버에 연결한 앱에서 이용해 주세요.');
            return;
          }
          Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => FacilitySearchScreen(api: facilityApi!),
            ),
          );
        },
      ),
      const SectionTitle('편리한 도우미'),
      ServiceGrid(
        children: [
          ServiceButton(
            title: '사진 도우미',
            subtitle: '안내문·약 봉투 살펴보기',
            icon: Icons.photo_camera_outlined,
            background: const Color(0xFFEAF3FC),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => NutritionScreen(
                  repository: repository,
                  settings: settings,
                  document: true,
                ),
              ),
            ),
          ),
          ServiceButton(
            title: '길·장소 도우미',
            subtitle: '약국·병원·주민센터 찾기',
            icon: Icons.map_outlined,
            background: const Color(0xFFF0EDFC),
            onTap: () => places(context),
          ),
        ],
      ),
      const SectionTitle('그 외 도우미'),
      ServiceGrid(
        children: [
          ServiceButton(
            title: 'AI 말동무',
            subtitle: '추천 질문으로 시작하기',
            icon: Icons.chat_bubble_outline_rounded,
            background: const Color(0xFFF3F3F5),
            onTap: () => chat(context),
          ),
          ServiceButton(
            title: '생활 도우미',
            subtitle: topicApi == null ? '앱 사용법 물어보기' : '생활 안내 보기 · 필요한 주제 요청',
            icon: Icons.lightbulb_outline_rounded,
            background: const Color(0xFFFFF3E4),
            onTap: () => topicApi == null
                ? chat(context)
                : Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => GuideCatalogScreen(
                        api: topicApi!,
                        settings: settings,
                      ),
                    ),
                  ),
          ),
        ],
      ),
      const SizedBox(height: 18),
      Text(
        aiApi == null
            ? '서버 연결이 없어 사용법 예시 대화를 제공해요.'
            : 'AI는 생활·요리 참고용이에요. 음식 사진은 영양분석에서 확인해 주세요. 안내문·약 봉투 AI 풀이는 아직 제공하지 않아요.',
        style: TextStyle(fontSize: 14, color: muted, height: 1.5),
      ),
    ],
  );
}

class ConversationScreen extends StatefulWidget {
  const ConversationScreen({required this.settings, this.api, super.key});
  final AppSettings settings;
  final AiApi? api;
  @override
  State<ConversationScreen> createState() => _ConversationScreenState();
}

class _ConversationScreenState extends State<ConversationScreen> {
  final input = TextEditingController();
  final scroll = ScrollController();
  bool _busy = false, _consented = false;
  String? _error;
  CancelToken? _request;
  final messages = <({bool user, String text})>[
    (user: false, text: '안녕하세요! 오늘동행 사용법을 안내해 드릴게요. 아래 질문을 눌러 보세요.'),
  ];
  static const answers = {
    '식단 추천은 어떻게 하나요?':
        '식단추천 화면에서 ‘식생활 서비스’를 누르고 사용자 정보를 입력해 주세요. 건강 상태, 알레르기 재료, 식사 시간을 선택하면 공공 레시피에서 추천해 드려요.',
    '복지 정보는 어디서 보나요?':
        '‘복지 추천’에서 나이, 거주 지역, 가구 형태와 소득 구간을 입력해 주세요. 복지로에서 가져온 전국 사업을 안내하고 지원대상과 선정기준도 볼 수 있어요.',
    '글자를 더 크게 보고 싶어요':
        '화면 오른쪽 위 설정 버튼을 눌러 ‘크게’ 또는 ‘아주 크게’를 선택해 주세요. 앱 전체 글자 크기가 바뀌어요.',
  };
  Future<void> send(String text) async {
    if (text.trim().isEmpty || _busy) return;
    if (widget.api != null) {
      setState(() {
        _busy = true;
        _error = null;
      });
      try {
        if (!_consented) {
          final allowed = await confirmAiProcessing(context, photo: false);
          if (!allowed || !mounted) return;
          setState(() => _consented = true);
        }
        _request = CancelToken();
        final answer = await widget.api!.chat(text, _request!);
        if (!mounted) return;
        setState(() {
          messages.add((user: true, text: text.trim()));
          messages.add((user: false, text: answer));
          input.clear();
        });
        _scrollToEnd();
      } on ApiException catch (error) {
        if (mounted) {
          setState(() {
            _error = error.message;
            input.text = text;
          });
        }
      } finally {
        if (mounted) setState(() => _busy = false);
      }
      return;
    }
    setState(() {
      messages.add((user: true, text: text.trim()));
      messages.add((
        user: false,
        text:
            answers[text.trim()] ??
            '지금은 미리 준비한 사용법 안내를 체험하는 화면이에요. 자유로운 AI 대화에는 서버와 AI 연결이 필요해요. 아래 추천 질문을 이용해 주세요.',
      ));
    });
    input.clear();
    _scrollToEnd();
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (scroll.hasClients) {
        scroll.animateTo(
          scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  void dispose() {
    _request?.cancel();
    input.dispose();
    scroll.dispose();
    widget.settings.stop();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('생활·요리 도우미'),
      actions: [
        Padding(
          padding: EdgeInsets.only(right: 16),
          child: Center(child: Tag(widget.api == null ? '예시 대화' : 'AI 대화')),
        ),
      ],
    ),
    body: Column(
      children: [
        Expanded(
          child: ListView(
            controller: scroll,
            padding: const EdgeInsets.all(20),
            children: [
              Notice(
                widget.api == null
                    ? '사용법을 안내하는 예시 대화예요. 건강 상담이나 진료를 대신하지 않아요.'
                    : 'AI가 만든 참고 답변이에요. 개인 건강기록을 적지 마세요. 진료나 복지 자격 확인을 대신하지 않아요.',
              ),
              if (_busy && _consented) const LinearProgressIndicator(),
              if (_error != null) Notice('$_error\n질문을 확인하고 다시 보내 주세요.'),
              const SizedBox(height: 20),
              for (final message in messages)
                Align(
                  alignment: message.user
                      ? Alignment.centerRight
                      : Alignment.centerLeft,
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 14),
                    padding: const EdgeInsets.all(17),
                    constraints: const BoxConstraints(maxWidth: 320),
                    decoration: BoxDecoration(
                      color: message.user ? green : Colors.white,
                      borderRadius: BorderRadius.circular(18),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          message.text,
                          style: TextStyle(
                            fontSize: 17,
                            height: 1.65,
                            color: message.user ? Colors.white : ink,
                          ),
                        ),
                        if (!message.user)
                          IconButton(
                            tooltip: '답변 읽어주기',
                            onPressed: () => readAloud(
                              context,
                              widget.settings,
                              message.text,
                            ),
                            icon: const Icon(
                              Icons.volume_up_outlined,
                              color: green,
                              size: 21,
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              const SizedBox(height: 10),
              for (final question in answers.keys)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: OutlinedButton(
                    onPressed: _busy ? null : () => send(question),
                    child: Text(question),
                  ),
                ),
            ],
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: input,
                    maxLength: 300,
                    enabled: !_busy,
                    textInputAction: TextInputAction.send,
                    decoration: const InputDecoration(
                      hintText: '궁금한 내용을 적어 주세요',
                      counterText: '',
                    ),
                    onSubmitted: send,
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                  tooltip: '질문 보내기',
                  onPressed: _busy ? null : () => send(input.text),
                  icon: const Icon(Icons.arrow_upward_rounded),
                ),
              ],
            ),
          ),
        ),
      ],
    ),
  );
}
