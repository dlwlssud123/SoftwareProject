import java.util.Base64

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val kakaoNativeKey = (findProperty("dart-defines") as? String)
    .orEmpty()
    .split(',')
    .filter { it.isNotEmpty() }
    .map { String(Base64.getDecoder().decode(it), Charsets.UTF_8) }
    .firstOrNull { it.startsWith("KAKAO_NATIVE_APP_KEY=") }
    ?.substringAfter('=')
    .orEmpty()

android {
    namespace = "com.valueflow.valueflow"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.valueflow.valueflow"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        manifestPlaceholders["kakaoAuthScheme"] = "kakao$kakaoNativeKey"
        manifestPlaceholders["kakaoAuthEnabled"] = kakaoNativeKey.isNotEmpty().toString()
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
