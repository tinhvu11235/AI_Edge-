param(
    [ValidateSet("4g", "8g")]
    [string]$Memory = "4g",

    [ValidateSet("simulated", "real")]
    [string]$Backend = "simulated",

    [string]$Image = "edge-voice-ptt-test:arm64"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ModelsDir = Join-Path $Root "models"

$asrBackend = "simulated"
$ttsBackend = "simulated"
if ($Backend -eq "real") {
    $asrBackend = "whisper-cpp"
    $ttsBackend = "piper"
}

docker run --rm `
    --platform linux/arm64 `
    --memory $Memory `
    --memory-swap $Memory `
    --cpus 4 `
    -e PYTHONPATH=/app/src `
    -v "${ModelsDir}:/app/models:ro" `
    $Image `
    python -m edge_voice_test.runtime --asr-backend $asrBackend --tts-backend $ttsBackend --duration 2 --loops 1 --redact-transcript
