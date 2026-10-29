import 'package:flutter/material.dart';

const ink = Color(0xFF17191C);
const muted = Color(0xFF60656E);
const green = Color(0xFF247653);
const blue = Color(0xFF096DD9);
const canvas = Colors.white;
const line = Color(0xFFDFE3E9);
const warm = Color(0xFFF5B95F);

ThemeData appTheme() => ThemeData(
  useMaterial3: true,
  scaffoldBackgroundColor: canvas,
  colorScheme: ColorScheme.fromSeed(seedColor: blue, surface: canvas),
  textTheme: const TextTheme(
    headlineLarge: TextStyle(
      fontSize: 25,
      fontWeight: FontWeight.w800,
      color: ink,
      height: 1.35,
    ),
    headlineSmall: TextStyle(
      fontSize: 22,
      fontWeight: FontWeight.w800,
      color: ink,
      height: 1.4,
    ),
    titleLarge: TextStyle(
      fontSize: 20,
      fontWeight: FontWeight.w700,
      color: ink,
    ),
    titleMedium: TextStyle(
      fontSize: 18,
      fontWeight: FontWeight.w700,
      color: ink,
    ),
    bodyLarge: TextStyle(fontSize: 18, color: ink, height: 1.6),
    bodyMedium: TextStyle(fontSize: 16, color: ink, height: 1.55),
    bodySmall: TextStyle(fontSize: 14, color: muted, height: 1.5),
  ),
  appBarTheme: const AppBarTheme(
    backgroundColor: canvas,
    surfaceTintColor: Colors.transparent,
    centerTitle: false,
    titleTextStyle: TextStyle(
      fontSize: 21,
      fontWeight: FontWeight.w700,
      color: ink,
    ),
  ),
  filledButtonTheme: FilledButtonThemeData(
    style: FilledButton.styleFrom(
      minimumSize: const Size(48, 56),
      backgroundColor: blue,
      textStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
    ),
  ),
  outlinedButtonTheme: OutlinedButtonThemeData(
    style: OutlinedButton.styleFrom(
      minimumSize: const Size(48, 52),
      foregroundColor: blue,
      textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      side: const BorderSide(color: line),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
    ),
  ),
  inputDecorationTheme: InputDecorationTheme(
    filled: true,
    fillColor: Colors.white,
    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: const BorderSide(color: line),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: const BorderSide(color: line),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: const BorderSide(color: blue, width: 2),
    ),
    labelStyle: const TextStyle(fontSize: 16, color: muted),
  ),
  dividerColor: line,
);
