import 'package:flutter/material.dart';
import 'usage_recorder.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';

class AppSettings extends ChangeNotifier {
  AppSettings({
    this.textScale = 1,
    this.voice = true,
    this.persist = false,
    this.usageSharing = false,
    this.mealPreferences,
  });
  double textScale;
  bool voice;
  bool usageSharing;
  final bool persist;
  List<String>? mealPreferences;
  FlutterTts? _tts;
  static Future<AppSettings> load() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getDouble('textScale') ?? 1;
    return AppSettings(
      textScale: saved.clamp(1, 1.4),
      voice: prefs.getBool('voice') ?? true,
      persist: true,
      usageSharing: prefs.getBool('usageSharingV1') ?? false,
      mealPreferences: prefs.getStringList('mealPreferences'),
    );
  }

  Future<void> rememberMealPreferences(List<String>? value) async {
    if (persist) {
      final prefs = await SharedPreferences.getInstance();
      final saved = value == null
          ? await prefs.remove('mealPreferences')
          : await prefs.setStringList('mealPreferences', value);
      if (!saved) throw StateError('Could not save meal preferences');
    }
    mealPreferences = value;
  }

  Future<void> setUsageSharing(bool value) async {
    if (persist) {
      final saved = await (await SharedPreferences.getInstance()).setBool(
        'usageSharingV1',
        value,
      );
      if (!saved) throw StateError('Could not save usage preference');
    }
    usageSharing = value;
    notifyListeners();
  }

  Future<void> setScale(double value) async {
    textScale = value.clamp(1, 1.4);
    UsageRecorder.current?.record(
      'setting_changed',
      'settings',
      action: 'change',
      settingKind: 'text_size',
      settingValue: textScale >= 1.4
          ? 'largest'
          : textScale >= 1.2
          ? 'large'
          : 'normal',
    );
    notifyListeners();
    if (persist) {
      await (await SharedPreferences.getInstance()).setDouble(
        'textScale',
        textScale,
      );
    }
  }

  Future<void> setVoice(bool value) async {
    voice = value;
    UsageRecorder.current?.record(
      'setting_changed',
      'settings',
      action: 'change',
      settingKind: 'voice',
      settingValue: value ? 'enabled' : 'disabled',
    );
    notifyListeners();
    if (!value) await stop();
    if (persist) {
      await (await SharedPreferences.getInstance()).setBool('voice', value);
    }
  }

  Future<void> read(String text) async {
    if (!voice) throw StateError('설정에서 음성 안내를 켜 주세요.');
    _tts ??= FlutterTts();
    await _tts!.setLanguage('ko-KR');
    await _tts!.setSpeechRate(0.42);
    await _tts!.stop();
    if (await _tts!.speak(text) != 1) throw StateError('한국어 음성 엔진을 확인해 주세요.');
    UsageRecorder.current?.record('read_aloud', 'settings', action: 'open');
  }

  Future<void> stop() async {
    await _tts?.stop();
  }
}
