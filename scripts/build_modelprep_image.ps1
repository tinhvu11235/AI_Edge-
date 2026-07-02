param(
    [string]$Image = "edge-voice-modelprep:local"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

docker buildx build `
    -t $Image `
    -f (Join-Path $Root "Dockerfile.modelprep") `
    --load `
    $Root
