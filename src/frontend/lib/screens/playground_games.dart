import 'package:flutter/material.dart';

import '../theme.dart';

class NumberOrderGame extends StatefulWidget {
  const NumberOrderGame({super.key});

  @override
  State<NumberOrderGame> createState() => _NumberOrderGameState();
}

class _NumberOrderGameState extends State<NumberOrderGame> {
  late List<int> numbers;
  int nextNumber = 1;
  String? hint;

  @override
  void initState() {
    super.initState();
    reset();
  }

  void reset() {
    numbers = List.generate(9, (index) => index + 1)..shuffle();
    nextNumber = 1;
    hint = null;
  }

  void choose(int number) {
    if (number < nextNumber || nextNumber > numbers.length) return;
    setState(() {
      if (number == nextNumber) {
        nextNumber++;
        hint = null;
      } else {
        hint = '$nextNumber부터 찾아볼까요? 천천히 눌러 주세요.';
      }
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('숫자 순서대로 누르기')),
    body: ListView(
      key: const Key('number-game-scroll'),
      padding: const EdgeInsets.all(20),
      children: [
        if (nextNumber > numbers.length)
          _GameFinished(
            message: '1부터 9까지 모두 찾았어요!',
            detail: '차근차근 잘하셨어요.',
            onRestart: () => setState(reset),
          )
        else ...[
          Text(
            '1부터 9까지 순서대로 눌러 주세요.',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          const Text('시간 제한 없이 천천히 즐겨요.'),
          const SizedBox(height: 20),
          Semantics(
            liveRegion: true,
            child: Text(
              '다음 숫자 $nextNumber',
              style: Theme.of(context).textTheme.headlineLarge,
            ),
          ),
          Text('찾은 숫자 ${nextNumber - 1} / 9'),
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) => Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                for (final number in numbers)
                  SizedBox(
                    width: (constraints.maxWidth - 24) / 3,
                    child: OutlinedButton(
                      key: Key('number-$number'),
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 18),
                        foregroundColor: blue,
                        disabledForegroundColor: green,
                        backgroundColor: number < nextNumber
                            ? const Color(0xFFE4EEDC)
                            : Colors.white,
                      ),
                      onPressed: number < nextNumber
                          ? null
                          : () => choose(number),
                      child: Semantics(
                        label: number < nextNumber
                            ? '$number, 찾았어요'
                            : '$number',
                        excludeSemantics: true,
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              '$number',
                              style: const TextStyle(
                                fontSize: 30,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            if (number < nextNumber)
                              const Icon(Icons.check_rounded, size: 20),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          if (hint != null) ...[
            const SizedBox(height: 16),
            Semantics(liveRegion: true, child: Text(hint!)),
          ],
          const SizedBox(height: 24),
          OutlinedButton(
            onPressed: () => setState(reset),
            child: const Text('새로 시작하기'),
          ),
        ],
      ],
    ),
  );
}

const _proverbs = [
  (
    beginning: '가는 말이 고와야',
    ending: '오는 말이 곱다',
    others: ['등잔 밑이 어둡다', '백지장도 맞들면 낫다'],
    meaning: '내가 먼저 좋은 말로 대하면 상대도 좋은 말로 답한다는 뜻이에요.',
  ),
  (
    beginning: '낮말은 새가 듣고',
    ending: '밤말은 쥐가 듣는다',
    others: ['고생 끝에 낙이 온다', '시작이 반이다'],
    meaning: '누가 들을지 모르니 언제나 말을 조심하라는 뜻이에요.',
  ),
  (
    beginning: '천 리 길도',
    ending: '한 걸음부터',
    others: ['그림의 떡', '티끌 모아 태산'],
    meaning: '큰일도 작은 시작부터 차근차근 해 나간다는 뜻이에요.',
  ),
  (
    beginning: '호랑이도',
    ending: '제 말 하면 온다',
    others: ['돌다리도 두들겨 보고 건너라', '하늘의 별 따기'],
    meaning: '어떤 사람 이야기를 하는데 마침 그 사람이 나타날 때 쓰는 말이에요.',
  ),
  (
    beginning: '세 살 버릇',
    ending: '여든까지 간다',
    others: ['금강산도 식후경', '아는 길도 물어 가라'],
    meaning: '어릴 때 생긴 습관은 오래 이어지기 쉽다는 뜻이에요.',
  ),
  (
    beginning: '콩 심은 데 콩 나고',
    ending: '팥 심은 데 팥 난다',
    others: ['구슬이 서 말이라도 꿰어야 보배', '웃는 얼굴에 침 못 뱉는다'],
    meaning: '어떤 일을 하느냐에 따라 그에 맞는 결과가 생긴다는 뜻이에요.',
  ),
  (
    beginning: '발 없는 말이',
    ending: '천 리 간다',
    others: ['소 잃고 외양간 고친다', '작은 고추가 맵다'],
    meaning: '소문이나 이야기는 멀리까지 빠르게 퍼진다는 뜻이에요.',
  ),
  (
    beginning: '우물 안',
    ending: '개구리',
    others: ['누워서 떡 먹기', '원숭이도 나무에서 떨어진다'],
    meaning: '자신이 아는 좁은 세상만 알고 더 넓은 세상을 모를 때 쓰는 말이에요.',
  ),
];

class ProverbGame extends StatefulWidget {
  const ProverbGame({super.key});

  @override
  State<ProverbGame> createState() => _ProverbGameState();
}

class _ProverbGameState extends State<ProverbGame> {
  final scrollController = ScrollController();
  late List<
    ({String beginning, String ending, List<String> others, String meaning})
  >
  questions;
  late List<String> options;
  int questionIndex = 0;
  int score = 0;
  String? selected;

  @override
  void initState() {
    super.initState();
    reset();
  }

  void reset() {
    questions = [..._proverbs]..shuffle();
    questions = questions.take(5).toList();
    questionIndex = 0;
    score = 0;
    prepareQuestion();
    if (scrollController.hasClients) scrollController.jumpTo(0);
  }

  @override
  void dispose() {
    scrollController.dispose();
    super.dispose();
  }

  void prepareQuestion() {
    selected = null;
    final question = questions[questionIndex];
    options = [question.ending, ...question.others]..shuffle();
  }

  void choose(String answer) {
    if (selected != null || questionIndex >= questions.length) return;
    setState(() {
      selected = answer;
      if (answer == questions[questionIndex].ending) score++;
    });
  }

  void next() {
    if (selected == null || questionIndex >= questions.length) return;
    setState(() {
      questionIndex++;
      if (questionIndex < questions.length) prepareQuestion();
    });
    scrollController.jumpTo(0);
  }

  @override
  Widget build(BuildContext context) {
    final finished = questionIndex == questions.length;
    final question = finished ? null : questions[questionIndex];
    return Scaffold(
      appBar: AppBar(title: const Text('속담 이어 맞히기')),
      body: ListView(
        key: const Key('proverb-game-scroll'),
        controller: scrollController,
        padding: const EdgeInsets.all(20),
        children: [
          if (finished)
            _GameFinished(
              message: '속담 다섯 개를 함께 떠올렸어요!',
              detail: '맞힌 속담 $score / ${questions.length}개',
              onRestart: () => setState(reset),
            )
          else ...[
            Text('${questionIndex + 1} / ${questions.length} 문제'),
            const SizedBox(height: 8),
            const Text('뒤에 이어질 말을 골라 주세요.'),
            const SizedBox(height: 20),
            Text(
              question!.beginning,
              key: const Key('proverb-question'),
              style: Theme.of(context).textTheme.headlineLarge,
            ),
            const SizedBox(height: 20),
            for (var index = 0; index < options.length; index++)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: OutlinedButton(
                  key: Key('proverb-option-$index'),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.all(16),
                    alignment: Alignment.centerLeft,
                    disabledForegroundColor: ink,
                    backgroundColor:
                        selected != null && options[index] == question.ending
                        ? const Color(0xFFE4EEDC)
                        : Colors.white,
                  ),
                  onPressed: selected == null
                      ? () => choose(options[index])
                      : null,
                  child: Text(options[index]),
                ),
              ),
            if (selected != null) ...[
              const SizedBox(height: 8),
              Semantics(
                liveRegion: true,
                child: Text(
                  selected == question.ending
                      ? '정답이에요!'
                      : '정답은 ‘${question.ending}’예요.',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              const SizedBox(height: 8),
              Text(question.meaning),
              const SizedBox(height: 24),
              FilledButton(
                key: const Key('proverb-next'),
                onPressed: next,
                child: Text(
                  questionIndex == questions.length - 1 ? '결과 보기' : '다음 문제',
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class _GameFinished extends StatelessWidget {
  const _GameFinished({
    required this.message,
    required this.detail,
    required this.onRestart,
  });

  final String message;
  final String detail;
  final VoidCallback onRestart;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const Icon(Icons.celebration_outlined, size: 64, color: green),
      const SizedBox(height: 20),
      Semantics(
        liveRegion: true,
        child: Text(
          message,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.headlineSmall,
        ),
      ),
      const SizedBox(height: 12),
      Text(detail, textAlign: TextAlign.center),
      const SizedBox(height: 28),
      FilledButton(onPressed: onRestart, child: const Text('다시 하기')),
      const SizedBox(height: 12),
      OutlinedButton(
        onPressed: () => Navigator.of(context).pop(),
        child: const Text('놀이터로 돌아가기'),
      ),
    ],
  );
}
