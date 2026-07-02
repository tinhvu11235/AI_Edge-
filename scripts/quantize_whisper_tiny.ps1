param(
    [string]$Image = "edge-voice-modelprep:local",
    [string[]]$Quants = @("q8_0", "q5_0", "q4_0")
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WhisperDir = Join-Path $Root "models\whisper"
$ModelIn = Join-Path $WhisperDir "ggml-tiny.bin"

if (-not (Test-Path -LiteralPath $ModelIn)) {
    throw "Missing model: $ModelIn"
}

foreach ($quant in $Quants) {
    $out = Join-Path $WhisperDir "ggml-tiny-$quant.bin"
    if (Test-Path -LiteralPath $out) {
        Write-Host "Already exists: $out"
        continue
    }
    docker run --rm `
        -v "${WhisperDir}:/models" `
        $Image `
        /models/ggml-tiny.bin "/models/ggml-tiny-$quant.bin" $quant
}

Get-ChildItem -LiteralPath (Join-Path $Root "models") -Recurse -File |
    Sort-Object FullName |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash)  $($_.Path.Substring($Root.Length + 1))" } |
    Set-Content -Encoding ASCII -Path (Join-Path $Root "models\SHA256SUMS.txt")
