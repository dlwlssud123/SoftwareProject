param(
    [string]$DeviceId = 'emulator-5554',
    [switch]$LaunchEmulator,
    [string]$EmulatorName = 'flutter_emulator',
    [switch]$Presentation
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$flutterCommand = (Get-Command flutter -ErrorAction Stop).Source
$flutterRoot = Split-Path -Parent (Split-Path -Parent $flutterCommand)
$dartExecutable = Join-Path $flutterRoot 'bin\cache\dart-sdk\bin\dart.exe'
$flutterSnapshot = Join-Path $flutterRoot 'bin\cache\flutter_tools.snapshot'
$androidSdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android\sdk' }
$adbExecutable = Join-Path $androidSdk 'platform-tools\adb.exe'

if ($LaunchEmulator) {
    $emulatorExecutable = Join-Path $androidSdk 'emulator\emulator.exe'
    if (-not (Test-Path -LiteralPath $emulatorExecutable)) {
        throw 'Android SDK emulator를 찾을 수 없습니다. ANDROID_HOME을 설정해 주세요.'
    }
    Start-Process -FilePath $emulatorExecutable -ArgumentList @('-avd', $EmulatorName, '-no-snapshot-load', '-no-boot-anim', '-gpu', 'host')
    & $adbExecutable -s $DeviceId wait-for-device
}

Push-Location $projectRoot
try {
    # Use the installed official tool directly, avoiding Windows batch bootstrap delays.
    if ($Presentation) {
        & $dartExecutable $flutterSnapshot --suppress-analytics build apk --release
        if ($LASTEXITCODE -ne 0) { throw '발표용 APK 빌드에 실패했습니다.' }
        & $adbExecutable -s $DeviceId wait-for-device
        if ($LASTEXITCODE -ne 0) { throw 'Android 기기에 연결할 수 없습니다.' }
        $bootDeadline = (Get-Date).AddMinutes(3)
        while ((& $adbExecutable -s $DeviceId shell getprop sys.boot_completed).Trim() -ne '1') {
            if ((Get-Date) -gt $bootDeadline) { throw '에뮬레이터 부팅 시간이 초과되었습니다.' }
            Start-Sleep -Seconds 1
        }
        & $adbExecutable -s $DeviceId install -r (Join-Path $projectRoot 'build\app\outputs\flutter-apk\app-release.apk')
        if ($LASTEXITCODE -ne 0) { throw '발표용 APK 설치에 실패했습니다.' }
        & $adbExecutable -s $DeviceId shell am force-stop com.valueflow.valueflow
        & $adbExecutable -s $DeviceId shell am start -W -n com.valueflow.valueflow/com.valueflow.valueflow.MainActivity
    } else {
        & $dartExecutable $flutterSnapshot --suppress-analytics run -d $DeviceId
    }
    if ($LASTEXITCODE -ne 0) { throw '앱 실행에 실패했습니다. 위의 Flutter 오류를 확인해 주세요.' }
} finally {
    Pop-Location
}
