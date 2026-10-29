import 'dart:io';
import 'package:integration_test/integration_test_driver_extended.dart';

Future<void> main() async {
  await integrationDriver(
    onScreenshot: (name, bytes, [args]) async {
      final directory = Directory('build/screenshots')
        ..createSync(recursive: true);
      File('${directory.path}/$name.png').writeAsBytesSync(bytes);
      return true;
    },
  );
}
