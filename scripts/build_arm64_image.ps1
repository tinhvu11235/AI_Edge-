param(
    [switch]$RealBackends,
    [string]$Image = "edge-voice-ptt-test:arm64"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$installReal = "0"
if ($RealBackends) {
    $installReal = "1"
}

docker buildx build `
    --platform linux/arm64 `
    -t $Image `
    -f (Join-Path $Root "Dockerfile.arm64") `
    --build-arg "INSTALL_REAL_BACKENDS=$installReal" `
    --load `
    $Root
