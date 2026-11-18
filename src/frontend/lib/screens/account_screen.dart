import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../services/account.dart';
import '../widgets/common.dart';
import 'saved_profile_screen.dart';

class AccountStartScreen extends StatelessWidget {
  const AccountStartScreen({required this.account, super.key});

  final Account account;

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
        children: [
          Text('오늘동행', style: Theme.of(context).textTheme.headlineLarge),
          const SizedBox(height: 12),
          const Text('내게 맞는 식단과 복지 서비스를 찾아보세요.'),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: account.busy ? null : account.startGuest,
            child: const Text('게스트로 시작하기'),
          ),
          if (account.kakaoEnabled) ...[
            const SizedBox(height: 12),
            KakaoLoginButton(
              onPressed: account.busy ? null : account.connectKakao,
            ),
          ],
          const SizedBox(height: 8),
          TextButton(
            onPressed: account.busy ? null : account.continueOffline,
            child: const Text('로그인 없이 둘러보기'),
          ),
          AccountFeedback(account: account),
        ],
      ),
    ),
  );
}

class AccountSettings extends StatelessWidget {
  const AccountSettings({required this.account, super.key});

  final Account account;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: account,
    builder: (context, _) {
      final session = account.session;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SectionTitle('계정'),
          if (session?.kakaoLinked == true) ...[
            const Text('카카오 계정으로 이용 중이에요.'),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: account.busy
                  ? null
                  : () async {
                      await account.logout();
                      if (!account.entered && context.mounted) {
                        Navigator.of(context).pop();
                      }
                    },
              child: const Text('로그아웃'),
            ),
          ] else ...[
            if (session == null)
              OutlinedButton(
                onPressed: account.busy ? null : account.startGuest,
                child: const Text('게스트로 시작하기'),
              )
            else
              const Text('게스트로 이용 중이에요.'),
            if (account.kakaoEnabled) ...[
              const SizedBox(height: 8),
              if (session != null) ...[
                const Text('카카오 계정을 연결하면 다른 기기에서도 같은 계정으로 이용할 수 있어요.'),
                const SizedBox(height: 8),
              ],
              KakaoLoginButton(
                onPressed: account.busy ? null : account.connectKakao,
              ),
            ],
          ],
          if (session != null) ...[
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: account.busy
                  ? null
                  : () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => SavedProfileScreen(
                          account: account,
                          token: session.token,
                        ),
                      ),
                    ),
              child: const Text('저장할 추천 조건 관리'),
            ),
          ],
          AccountFeedback(account: account),
        ],
      );
    },
  );
}

class KakaoLoginButton extends StatelessWidget {
  const KakaoLoginButton({required this.onPressed, super.key});

  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) => FilledButton.icon(
    style: FilledButton.styleFrom(
      foregroundColor: const Color(0xD9000000),
      backgroundColor: const Color(0xFFFEE500),
      minimumSize: const Size(0, 56),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    onPressed: onPressed,
    icon: SvgPicture.asset(
      'assets/images/icon_talk_login.svg',
      package: 'kakao_flutter_sdk_user',
      width: 24,
      height: 24,
      colorFilter: const ColorFilter.mode(Colors.black, BlendMode.srcIn),
    ),
    label: const Text('카카오 로그인'),
  );
}

class AccountFeedback extends StatelessWidget {
  const AccountFeedback({required this.account, super.key});

  final Account account;

  @override
  Widget build(BuildContext context) {
    if (account.busy) {
      return const Column(
        children: [
          SizedBox(height: 12),
          LinearProgressIndicator(semanticsLabel: '계정 확인 중'),
        ],
      );
    }
    final message = account.message;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (message != null)
          Semantics(liveRegion: true, child: Notice(message)),
        if (account.linkConflict)
          OutlinedButton(
            onPressed: account.busy
                ? null
                : () async {
                    final accept = await showDialog<bool>(
                      context: context,
                      builder: (context) => AlertDialog(
                        title: const Text('기존 계정으로 로그인할까요?'),
                        content: const Text(
                          '현재 게스트 기록은 기존 계정에 합쳐지지 않아요. 기존 계정에 저장된 식단과 레시피를 불러와요.',
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(context, false),
                            child: const Text('취소'),
                          ),
                          FilledButton(
                            onPressed: () => Navigator.pop(context, true),
                            child: const Text('로그인'),
                          ),
                        ],
                      ),
                    );
                    if (accept == true) {
                      final previous = account.session?.userId;
                      await account.signInExistingKakao();
                      if (account.session?.userId != previous &&
                          context.mounted) {
                        Navigator.of(
                          context,
                        ).popUntil((route) => route.isFirst);
                      }
                    }
                  },
            child: const Text('기존 계정으로 로그인'),
          ),
      ],
    );
  }
}
