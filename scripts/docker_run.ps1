$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Results = Join-Path $Root "benchmark_results"
New-Item -ItemType Directory -Force -Path $Results | Out-Null

docker run --rm `
  --platform linux/arm64/v8 `
  -v "${Results}:/app/results" `
  ai-edge-pi5-voice:local `
  --audio=null `
  --iterations=5 `
  --out=/app/results/benchmark.jsonl
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
