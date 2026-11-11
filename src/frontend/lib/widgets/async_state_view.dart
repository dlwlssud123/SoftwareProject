import 'package:flutter/material.dart';

import '../core/network/api_exception.dart';

/// 서버 데이터를 보여주는 화면의 공통 상태 처리.
///
/// 우선순위: 불러오는 중 → 오류 → 빈 결과 → 내용.
/// 재시도할 수 있는 오류면 '다시 시도' 버튼을 보여준다.
class AsyncStateView extends StatelessWidget {
  const AsyncStateView({
    super.key,
    required this.loading,
    required this.isEmpty,
    required this.builder,
    this.error,
    this.onRetry,
    this.loadingMessage = '불러오는 중이에요',
    this.emptyMessage = '아직 보여드릴 내용이 없어요',
  });

  final bool loading;
  final bool isEmpty;
  final WidgetBuilder builder;
  final ApiException? error;
  final VoidCallback? onRetry;
  final String loadingMessage;
  final String emptyMessage;

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return _StateMessage(
        leading: const CircularProgressIndicator(),
        message: loadingMessage,
      );
    }
    final currentError = error;
    if (currentError != null) {
      return _StateMessage(
        leading: const Icon(Icons.error_outline, size: 48),
        message: currentError.message,
        action: onRetry != null && currentError.canRetry
            ? FilledButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('다시 시도'),
              )
            : null,
      );
    }
    if (isEmpty) {
      return _StateMessage(
        leading: const Icon(Icons.inbox_outlined, size: 48),
        message: emptyMessage,
      );
    }
    return builder(context);
  }
}

class _StateMessage extends StatelessWidget {
  const _StateMessage({required this.leading, required this.message, this.action});

  final Widget leading;
  final String message;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final currentAction = action;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            leading,
            const SizedBox(height: 16),
            Text(
              message,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (currentAction != null) ...[
              const SizedBox(height: 20),
              currentAction,
            ],
          ],
        ),
      ),
    );
  }
}
