import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'data/demo_repository.dart';
import 'data/recipe_api.dart';
import 'data/intake_api.dart';
import 'data/welfare_api.dart';
import 'data/topic_api.dart';
import 'data/facility_api.dart';
import 'data/ai_api.dart';
import 'data/health_video_api.dart';
import 'services/settings.dart';
import 'services/account.dart';
import 'theme.dart';
import 'screens/meal_screen.dart';
import 'screens/assistant_screen.dart';
import 'screens/nutrition_screen.dart';
import 'screens/content_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/account_screen.dart';

class ValueFlowApp extends StatelessWidget {
  const ValueFlowApp({
    required this.repository,
    required this.settings,
    this.recipeApi,
    this.account,
    this.intakeApi,
    this.welfareApi,
    this.topicApi,
    this.facilityApi,
    this.aiApi,
    this.healthVideoApi,
    super.key,
  });
  final DemoRepository repository;
  final AppSettings settings;

  /// null이면 서버 없이 데모 데이터만 쓴다.
  final RecipeApi? recipeApi;
  final Account? account;
  final IntakeApi? intakeApi;
  final WelfareApi? welfareApi;
  final TopicApi? topicApi;
  final FacilityApi? facilityApi;
  final AiApi? aiApi;
  final HealthVideoApi? healthVideoApi;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: settings,
    builder: (context, child) => MaterialApp(
      title: '오늘동행 · ValueFlow',
      debugShowCheckedModeBanner: false,
      theme: appTheme(),
      scrollBehavior: const MaterialScrollBehavior().copyWith(
        overscroll: false,
      ),
      locale: const Locale('ko'),
      supportedLocales: const [Locale('ko')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      builder: (context, child) => settings.textScale == 1
          ? child!
          : MediaQuery.withClampedTextScaling(
              minScaleFactor: settings.textScale,
              child: child!,
            ),
      home: _home(),
    ),
  );

  Widget _home() {
    Widget shell() => AppShell(
      key: ValueKey(account?.session?.userId),
      repository: repository,
      settings: settings,
      recipeApi: recipeApi,
      account: account,
      intakeApi: intakeApi,
      welfareApi: welfareApi,
      topicApi: topicApi,
      facilityApi: facilityApi,
      aiApi: aiApi,
      healthVideoApi: healthVideoApi,
    );
    final auth = account;
    if (auth == null) return shell();
    return ListenableBuilder(
      listenable: auth,
      builder: (_, _) =>
          auth.entered ? shell() : AccountStartScreen(account: auth),
    );
  }
}

class AppShell extends StatefulWidget {
  const AppShell({
    required this.repository,
    required this.settings,
    this.recipeApi,
    this.account,
    this.intakeApi,
    this.welfareApi,
    this.topicApi,
    this.facilityApi,
    this.aiApi,
    this.healthVideoApi,
    super.key,
  });
  final DemoRepository repository;
  final AppSettings settings;
  final RecipeApi? recipeApi;
  final Account? account;
  final IntakeApi? intakeApi;
  final WelfareApi? welfareApi;
  final TopicApi? topicApi;
  final FacilityApi? facilityApi;
  final AiApi? aiApi;
  final HealthVideoApi? healthVideoApi;
  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  static const initialTab = 0;
  int selected = initialTab;
  final visitedTabs = <int>{initialTab};
  final navigators = List.generate(
    labels.length,
    (_) => GlobalKey<NavigatorState>(),
  );
  late final List<Widget> pages = [
    MealScreen(
      repository: widget.repository,
      settings: widget.settings,
      recipeApi: widget.recipeApi,
      account: widget.account,
    ),
    NutritionScreen(
      repository: widget.repository,
      settings: widget.settings,
      intakeApi: widget.intakeApi,
      aiApi: widget.aiApi,
    ),
    AssistantScreen(
      repository: widget.repository,
      settings: widget.settings,
      welfareApi: widget.welfareApi,
      topicApi: widget.topicApi,
      facilityApi: widget.facilityApi,
      aiApi: widget.aiApi,
    ),
    ContentScreen(
      settings: widget.settings,
      topicApi: widget.topicApi,
      healthVideoApi: widget.healthVideoApi,
    ),
  ];
  static const labels = ['식단추천', '영양분석', 'AI 도우미', '놀이터'];
  static const icons = [
    Icons.restaurant_rounded,
    Icons.document_scanner_outlined,
    Icons.chat_bubble_outline_rounded,
    Icons.sports_esports_rounded,
  ];
  @override
  Widget build(BuildContext context) => Scaffold(
    body: IndexedStack(
      index: selected,
      children: List.generate(
        labels.length,
        (index) => !visitedTabs.contains(index)
            ? const SizedBox.shrink()
            : TickerMode(
                enabled: selected == index,
                child: NavigatorPopHandler<Object?>(
                  enabled: selected == index,
                  onPopWithResult: (result) =>
                      navigators[index].currentState!.maybePop(result),
                  child: Navigator(
                    key: navigators[index],
                    onGenerateRoute: (_) => MaterialPageRoute<void>(
                      builder: (_) => Scaffold(
                        appBar: AppBar(
                          title: Text(labels[index]),
                          actions: [
                            IconButton(
                              key: const Key('settings-button'),
                              tooltip: '글자 크기와 음성 설정',
                              icon: const Icon(Icons.settings, color: blue),
                              onPressed: () => Navigator.of(context).push(
                                MaterialPageRoute<void>(
                                  builder: (_) => SettingsScreen(
                                    settings: widget.settings,
                                    account: widget.account,
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                        body: pages[index],
                      ),
                    ),
                  ),
                ),
              ),
      ),
    ),
    bottomNavigationBar: DecoratedBox(
      decoration: const BoxDecoration(
        color: Color(0xFFF2F2F5),
        border: Border(top: BorderSide(color: line)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 7),
          child: Row(
            children: List.generate(
              labels.length,
              (i) => Expanded(
                child: Semantics(
                  selected: selected == i,
                  button: true,
                  label: labels[i],
                  child: InkWell(
                    key: Key('tab-$i'),
                    onTap: () {
                      widget.settings.stop();
                      if (selected == i) {
                        final navigator = navigators[i].currentState!;
                        navigator.popUntil((route) {
                          if (route.isFirst) return true;
                          // Respect unsaved/saving forms before returning home.
                          if (route.popDisposition ==
                              RoutePopDisposition.doNotPop) {
                            navigator.maybePop();
                            return true;
                          }
                          return false;
                        });
                      }
                      setState(() {
                        visitedTabs.add(i);
                        selected = i;
                      });
                    },
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(minHeight: 58),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 3),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            SizedBox(
                              height: 32,
                              child: Icon(
                                icons[i],
                                size: 26,
                                color: selected == i
                                    ? blue
                                    : const Color(0xFF80858D),
                              ),
                            ),
                            const SizedBox(height: 4),
                            FittedBox(
                              fit: BoxFit.scaleDown,
                              child: Text(
                                labels[i],
                                style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: selected == i
                                      ? FontWeight.w700
                                      : FontWeight.w500,
                                  color: selected == i
                                      ? blue
                                      : const Color(0xFF60656E),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}
