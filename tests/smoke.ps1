# Exercise every command against a throwaway BepInEx tree, on Windows.
# Windows counterpart of smoke.sh - same commands, same pass/fail output.
#
#   powershell -ExecutionPolicy Bypass -File tests\smoke.ps1
#
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("beastfly-smoke-" + [guid]::NewGuid())
$env:BEASTFLY_HOME = Join-Path $Work "home"
$Game = Join-Path $Work "game\Hollow Knight Silksong"
$Downloads = Join-Path $Work "downloads"

try {
    foreach ($dir in @("$Game\BepInEx\plugins", "$Game\BepInEx\patchers",
                       "$Game\BepInEx\core", "$Game\Hollow Knight Silksong_Data",
                       $Downloads,
                       "$Game\BepInEx\plugins\CanvasUtil",
                       "$Game\BepInEx\plugins\prepatcher",
                       "$Game\BepInEx\patchers\prepatcher",
                       "$Game\BepInEx\plugins\QoL\ToggleHUD-28-2-0-4-1758980847")) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    foreach ($file in @("$Game\Hollow Knight Silksong.exe",
                        "$Game\BepInEx\core\BepInEx.dll",
                        "$Game\BepInEx\plugins\CanvasUtil\CanvasUtil.dll",
                        "$Game\BepInEx\plugins\prepatcher\Plugin.dll",
                        "$Game\BepInEx\patchers\prepatcher\Patcher.dll",
                        "$Game\BepInEx\plugins\QoL\ToggleHUD-28-2-0-4-1758980847\ToggleHUD.dll")) {
        New-Item -ItemType File -Force -Path $file | Out-Null
    }

    $env:PYTHONPATH = $Root
    python - $Game $Downloads @"
import json, sys, zipfile
from beastfly.config import Config
c = Config()
c["game_path"] = sys.argv[1]
c["downloads_path"] = sys.argv[2]
c["wrapper_path"] = ""
c["backup_saves_on_launch"] = False
with zipfile.ZipFile(sys.argv[2] + "/TestMod.zip", "w") as f:
    f.writestr("manifest.json", json.dumps({
        "name": "TestMod", "namespace": "tester", "version_number": "1.0.0",
        "description": "smoke test", "dependencies": []}))
    f.writestr("plugins/TestMod.dll", b"MZ")
    f.writestr("patchers/TestModPatcher.dll", b"MZ")
"@

    $failed = 0
    function Run([string]$command) {
        $arguments = $command.Split(" ")
        $output = ("n`nn`n" | python -m beastfly @arguments 2>&1 | Out-String)
        if ($output -match "Traceback") {
            Write-Host "FAIL  /$command"
            Write-Host ($output -split "`n" | Select-Object -First 25 | Out-String)
            $script:failed += 1
        } else {
            Write-Host "ok    /$command"
        }
    }

    foreach ($command in @(
        "toggle", "toggle canvasutil", "toggle canvasutil", "ls", "ls --disabled",
        "add", "add TestMod", "info TestMod", "remove TestMod", "updates", "missing",
        "profiles", "profiles create Second", "profiles Second", "profiles save Second",
        "profiles rename Second Third", "profiles delete Third",
        "backup", "backup list", "launch", "logs 5", "path", "settings",
        "settings auto_update on", "help", "help toggle", "bogus", "--version")) {
        Run $command
    }

    Write-Host "------------------------------"
    if ($failed -eq 0) {
        Write-Host "all checks passed"
    } else {
        Write-Host "$failed failed"
        exit 1
    }
}
finally {
    Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
}
