param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Path
)

$ErrorActionPreference = "Stop"

function New-Issue {
    param(
        [string]$Severity,
        [int]$Line,
        [string]$Message
    )
    [PSCustomObject]@{
        Severity = $Severity
        Line = $Line
        Message = $Message
    }
}

function Print-Issues {
    param([array]$Items)
    foreach ($item in $Items) {
        if ($item.Line -gt 0) {
            Write-Host ("[{0}] line {1}: {2}" -f $item.Severity, $item.Line, $item.Message)
        } else {
            Write-Host ("[{0}] {1}" -f $item.Severity, $item.Message)
        }
    }
}

$issues = @()

$resolvedPath = Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue
if (-not $resolvedPath) {
    Write-Host "[ERROR] File not found: $Path"
    exit 2
}

$filePath = $resolvedPath.Path
if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
    Write-Host "[ERROR] Not a file: $filePath"
    exit 2
}

$extension = [System.IO.Path]::GetExtension($filePath)
if ($extension -ne ".pine") {
    $issues += New-Issue -Severity "WARN" -Line 0 -Message "File extension is '$extension' (recommended: .pine)."
}

$content = Get-Content -LiteralPath $filePath -Raw
if ([string]::IsNullOrWhiteSpace($content)) {
    Write-Host "[ERROR] File is empty."
    exit 2
}

$lines = Get-Content -LiteralPath $filePath

$versionLine = $null
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*//@version\s*=\s*\d+\s*$') {
        $versionLine = $i + 1
        if ($lines[$i] -notmatch '^\s*//@version\s*=\s*6\s*$') {
            $issues += New-Issue -Severity "WARN" -Line ($i + 1) -Message "Script version is not v6."
        }
        break
    }
}
if (-not $versionLine) {
    $issues += New-Issue -Severity "ERROR" -Line 1 -Message "Missing Pine version directive (expected //@version=6)."
}

$declLine = $null
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '\b(indicator|strategy|library)\s*\(') {
        $declLine = $i + 1
        break
    }
}
if (-not $declLine) {
    $issues += New-Issue -Severity "ERROR" -Line 1 -Message "Missing top-level indicator()/strategy()/library() declaration."
}

for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "`t") {
        $issues += New-Issue -Severity "WARN" -Line ($i + 1) -Message "Tab character detected; Pine formatting is more stable with spaces."
    }
}

$stack = New-Object System.Collections.Generic.List[Object]
$inString = $false
$stringQuote = [char]0
$inBlockComment = $false

for ($lineIndex = 0; $lineIndex -lt $lines.Count; $lineIndex++) {
    $line = $lines[$lineIndex]
    $charIndex = 0
    while ($charIndex -lt $line.Length) {
        $ch = $line[$charIndex]
        $next = if ($charIndex + 1 -lt $line.Length) { $line[$charIndex + 1] } else { [char]0 }

        if ($inBlockComment) {
            if ($ch -eq '*' -and $next -eq '/') {
                $inBlockComment = $false
                $charIndex += 2
                continue
            }
            $charIndex++
            continue
        }

        if (-not $inString) {
            if ($ch -eq '/' -and $next -eq '/') {
                break
            }
            if ($ch -eq '/' -and $next -eq '*') {
                $inBlockComment = $true
                $charIndex += 2
                continue
            }
        }

        if ($ch -eq '"' -or $ch -eq "'") {
            if (-not $inString) {
                $inString = $true
                $stringQuote = $ch
            } elseif ($stringQuote -eq $ch) {
                $prev = if ($charIndex -gt 0) { $line[$charIndex - 1] } else { [char]0 }
                if ($prev -ne '\') {
                    $inString = $false
                    $stringQuote = [char]0
                }
            }
            $charIndex++
            continue
        }

        if ($inString) {
            $charIndex++
            continue
        }

        if ($ch -eq '(' -or $ch -eq '[' -or $ch -eq '{') {
            $stack.Add([PSCustomObject]@{
                Char = $ch
                Line = $lineIndex + 1
            }) | Out-Null
        } elseif ($ch -eq ')' -or $ch -eq ']' -or $ch -eq '}') {
            if ($stack.Count -eq 0) {
                $issues += New-Issue -Severity "ERROR" -Line ($lineIndex + 1) -Message ("Unexpected closing '{0}'." -f $ch)
            } else {
                $last = $stack[$stack.Count - 1]
                $stack.RemoveAt($stack.Count - 1)
                $expected = switch ($last.Char) {
                    '(' { ')' }
                    '[' { ']' }
                    '{' { '}' }
                    default { '?' }
                }
                if ($ch -ne $expected) {
                    $issues += New-Issue -Severity "ERROR" -Line ($lineIndex + 1) -Message ("Mismatched closing '{0}' for opening '{1}' from line {2}." -f $ch, $last.Char, $last.Line)
                }
            }
        }

        $charIndex++
    }
}

if ($inString) {
    $issues += New-Issue -Severity "ERROR" -Line $lines.Count -Message "Unterminated string literal."
}
if ($inBlockComment) {
    $issues += New-Issue -Severity "ERROR" -Line $lines.Count -Message "Unterminated block comment."
}
foreach ($open in $stack) {
    $issues += New-Issue -Severity "ERROR" -Line $open.Line -Message ("Unclosed '{0}'." -f $open.Char)
}

for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -match 'request\.security\s*\(.*lookahead\s*=\s*barmerge\.lookahead_on') {
        $issues += New-Issue -Severity "WARN" -Line ($i + 1) -Message "lookahead_on can repaint historical signals."
    }
    if ($line -match 'for\s+\w+\s*=\s*0\s+to\s+array\.size\([^)]+\)\s*-\s*1') {
        $issues += New-Issue -Severity "WARN" -Line ($i + 1) -Message "Loop uses array.size(...)-1; ensure array is non-empty before iteration."
    }
    if ($line -match 'runtime\.error\s*\(') {
        $issues += New-Issue -Severity "INFO" -Line ($i + 1) -Message "runtime.error() found; verify this is intended for production."
    }
}

$errorCount = ($issues | Where-Object { $_.Severity -eq "ERROR" }).Count
$warnCount = ($issues | Where-Object { $_.Severity -eq "WARN" }).Count
$infoCount = ($issues | Where-Object { $_.Severity -eq "INFO" }).Count

Write-Host ("Validating: {0}" -f $filePath)
Write-Host ("Lines: {0}" -f $lines.Count)

if ($issues.Count -gt 0) {
    Print-Issues -Items $issues
} else {
    Write-Host "[OK] No issues found by local static checks."
}

Write-Host ("Summary: {0} error(s), {1} warning(s), {2} info item(s)." -f $errorCount, $warnCount, $infoCount)

if ($errorCount -gt 0) {
    exit 1
}

exit 0
