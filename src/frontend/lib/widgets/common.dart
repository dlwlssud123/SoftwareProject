import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../theme.dart';
import '../services/settings.dart';

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.title, {this.trailing, super.key});
  final String title;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 20, bottom: 10),
    child: Row(
      children: [
        Expanded(
          child: Text(title, style: Theme.of(context).textTheme.titleLarge),
        ),
        ?trailing,
      ],
    ),
  );
}

class FeatureTile extends StatelessWidget {
  const FeatureTile({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.onTap,
    this.color = green,
    this.background,
    super.key,
  });
  final String title, subtitle;
  final IconData icon;
  final VoidCallback onTap;
  final Color color;
  final Color? background;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Material(
      color: background ?? Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: background == null ? line : color.withValues(alpha: .20),
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 48,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(icon, color: color, size: 29),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 4),
                    Text(
                      subtitle,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 5),
              const Icon(Icons.chevron_right_rounded, color: muted),
            ],
          ),
        ),
      ),
    ),
  );
}

class Notice extends StatelessWidget {
  const Notice(
    this.text, {
    this.icon = Icons.info_outline_rounded,
    this.color = green,
    super.key,
  });
  final String text;
  final IconData icon;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .07),
      borderRadius: BorderRadius.circular(10),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 20, color: color),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            text,
            style: TextStyle(fontSize: 14, height: 1.6, color: color),
          ),
        ),
      ],
    ),
  );
}

class Tag extends StatelessWidget {
  const Tag(this.text, {this.color = green, super.key});
  final String text;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .08),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Text(
      text,
      style: TextStyle(fontSize: 13, color: color, fontWeight: FontWeight.w600),
    ),
  );
}

class ServiceGrid extends StatelessWidget {
  const ServiceGrid({required this.children, super.key});
  final List<Widget> children;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final columns =
          constraints.maxWidth < 320 &&
              MediaQuery.textScalerOf(context).scale(1) > 1.2
          ? 1
          : 2;
      final width = (constraints.maxWidth - 10 * (columns - 1)) / columns;
      return Wrap(
        spacing: 10,
        runSpacing: 10,
        children: children
            .map((child) => SizedBox(width: width, child: child))
            .toList(),
      );
    },
  );
}

class ServiceButton extends StatelessWidget {
  const ServiceButton({
    required this.title,
    required this.icon,
    required this.onTap,
    this.subtitle,
    this.background = const Color(0xFFF1F5FC),
    this.foreground = ink,
    super.key,
  });
  final String title;
  final String? subtitle;
  final IconData icon;
  final VoidCallback onTap;
  final Color background, foreground;
  @override
  Widget build(BuildContext context) => Material(
    color: background,
    borderRadius: BorderRadius.circular(10),
    child: InkWell(
      borderRadius: BorderRadius.circular(10),
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 74),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, size: 28, color: foreground),
              const SizedBox(height: 9),
              Text(
                title,
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: foreground,
                  height: 1.35,
                ),
              ),
              if (subtitle != null) ...[
                const SizedBox(height: 5),
                Text(
                  subtitle!,
                  style: TextStyle(
                    fontSize: 14,
                    color: foreground,
                    height: 1.45,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    ),
  );
}

void showMessage(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
  );
}

Future<void> openLink(BuildContext context, Uri uri) async {
  try {
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      throw StateError('no handler');
    }
  } catch (_) {
    if (context.mounted) {
      showMessage(context, '연결할 수 없어요. 인터넷 연결과 브라우저를 확인해 주세요.');
    }
  }
}

Future<void> readAloud(
  BuildContext context,
  AppSettings settings,
  String text,
) async {
  try {
    await settings.read(text);
  } catch (_) {
    if (context.mounted) {
      showMessage(context, '음성 안내를 사용할 수 없어요. 설정과 기기의 한국어 음성을 확인해 주세요.');
    }
  }
}
