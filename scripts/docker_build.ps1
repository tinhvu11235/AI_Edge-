$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$BuildTag = "ai-edge-pi5-voice:build-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
Push-Location $Root
try {
  docker buildx build `
    --platform linux/arm64/v8 `
    -f docker/Dockerfile.pi5 `
    -t $BuildTag `
    --load `
    .
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
  docker image tag $BuildTag ai-edge-pi5-voice:local
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
finally {
  Pop-Location
}
