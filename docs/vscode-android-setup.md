# VS Code Android Setup

## Installed Extensions

Installed VS Code extensions for Android development without Android Studio:

- `fwcd.kotlin` - Kotlin language server, completion, linting, debugging.
- `vscjava.vscode-gradle` - Gradle projects and tasks in VS Code.
- `redhat.java` - Java language support for Gradle/JVM projects.
- `vscjava.vscode-java-debug` - Java debugger for JVM workflows.
- `adelphes.android-dev-ext` - Android deploy, launch, debug and Logcat via ADB.

## Installed Tools

The local machine now has the command-line toolchain needed to build the debug APK:

- JDK 21: `C:\Program Files\Eclipse Adoptium\jdk-21.0.11.10-hotspot`
- Android SDK: `%LOCALAPPDATA%\Android\Sdk`
- Android SDK Platform Tools: `adb`
- Android platform: `android-35`
- Android Build Tools: `35.0.0`
- Gradle wrapper: `android/gradlew.bat`

The project uses `android.overridePathCheck=true` because the workspace path contains Cyrillic characters. This is acceptable for local development, but a plain ASCII path is safer for CI.

## Build APK

```powershell
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-21.0.11.10-hotspot"
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:Path = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:Path"

cd android
.\gradlew.bat assembleDebug
```

Build output:

```text
android/app/build/outputs/apk/debug/app-debug.apk
reports/purchase-forecast-debug.apk
```

## VS Code Workflow

1. Open `projects/purchase-forecast-service` in VS Code.
2. Check that recommended extensions are enabled.
3. Open Gradle view and enable nested project detection if `android/` is not discovered automatically.
4. Run task `android: assemble debug`.
5. Connect an Android phone with USB debugging enabled.
6. Run launch configuration `Android: build and launch debug APK`.

## Notes

- The current APK is a debug build and is suitable for local testing only.
- Release APK signing is not configured yet.
- The Android app currently uses static demo data; the next step is moving the Python purchase-calendar logic to Kotlin and adding local storage.
