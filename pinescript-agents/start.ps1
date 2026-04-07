Write-Host "Pine Script Development Assistant"
Write-Host "================================="
Write-Host ""

$stateDir = ".codex"
$onboardingFile = "$stateDir/.onboarding_complete"
$legacyOnboardingFile1 = ".assistant/.onboarding_complete"
$legacyOnboardingFile2 = ".claude/.onboarding_complete"

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
if ((Test-Path $legacyOnboardingFile1) -and -not (Test-Path $onboardingFile)) {
    New-Item -ItemType File -Force -Path $onboardingFile | Out-Null
} elseif ((Test-Path $legacyOnboardingFile2) -and -not (Test-Path $onboardingFile)) {
    New-Item -ItemType File -Force -Path $onboardingFile | Out-Null
}

if (-not (Test-Path $onboardingFile)) {
    Write-Host "Welcome! This appears to be your first run."
    Write-Host ""
    Write-Host "This workspace helps you build TradingView Pine Scripts with Codex."
    Write-Host ""
    Write-Host "Try one of these prompts in Codex:"
    Write-Host "  - Create an RSI divergence indicator with alerts."
    Write-Host "  - Build a moving average crossover strategy with risk controls."
    Write-Host "  - Analyze this video: https://youtube.com/watch?v=..."
    Write-Host ""

    New-Item -ItemType File -Force -Path $onboardingFile | Out-Null
} else {
    Write-Host "System ready."
    Write-Host ""
}

if (-not (Test-Path "projects")) {
    New-Item -ItemType Directory -Force -Path "projects" | Out-Null
}

if (-not (Test-Path "projects/blank.pine")) {
    @'
//@version=6
// This is a blank Pine Script template
// It will be renamed and populated based on your requirements
//
// Project: [To be defined]
// Type: [Indicator/Strategy]
// Created: [Date]
//
// ============================================================================

indicator("Blank Template", overlay=true)

// Your Pine Script code will be generated here
'@ | Set-Content "projects/blank.pine"
}

Write-Host "Next step: describe what you want to build in Codex."
