import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';

class AppSettings extends ChangeNotifier {
  AppSettings({this.textScale = 1, this.voice = true, this.persist = false});
  double textScale;
  bool voice;
  final bool persist;
  FlutterTts? _tts;
  static Future<AppSettings> load() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getDouble('textScale') ?? 1;
    return AppSettings(
      textScale: saved.clamp(1, 1.4),
      voice: prefs.getBool('voice') ?? true,
      persist: true,
    );
  }

  Future<void> setScale(double value) async {
    textScale = value.clamp(1, 1.4);
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
  }

  Future<void> stop() async {
    await _tts?.stop();
  }
}
