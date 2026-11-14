import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'data/demo_repository.dart';
import 'services/settings.dart';
import 'theme.dart';
import 'screens/meal_screen.dart';
import 'screens/assistant_screen.dart';
import 'screens/nutrition_screen.dart';
import 'screens/content_screen.dart';
import 'screens/settings_screen.dart';

class ValueFlowApp extends StatelessWidget {
  const ValueFlowApp({
    required this.repository,
    required this.settings,
    super.key,
  });
  final DemoRepository repository;
  final AppSettings settings;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: settings,
    builder: (context, child) => MaterialApp(
      title: '오늘동행 · ValueFlow',
      debugShowCheckedModeBanner: false,
      theme: appTheme(),
      scrollBehavior: const MaterialScrollBehavior().copyWith(overscroll: false),
      locale: const Locale('ko'),
      supportedLocales: const [Locale('ko')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(settings.textScale)),
        child: child!,
      ),
      home: AppShell(repository: repository, settings: settings),
    ),
  );
}

class AppShell extends StatefulWidget {
  const AppShell({required this.repository, required this.settings, super.key});
  final DemoRepository repository;
  final AppSettings settings;
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
    MealScreen(repository: widget.repository, settings: widget.settings),
    NutritionScreen(repository: widget.repository, settings: widget.settings),
    AssistantScreen(repository: widget.repository, settings: widget.settings),
    const ContentScreen(),
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
                      navigators[index].currentState!.pop(result),
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
                                  builder: (_) =>
                                      SettingsScreen(settings: widget.settings),
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
                        navigators[i].currentState!.popUntil(
                          (route) => route.isFirst,
                        );
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
