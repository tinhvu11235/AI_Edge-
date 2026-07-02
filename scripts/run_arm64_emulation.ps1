param(
    [ValidateSet("4g", "8g")]
    [string]$Memory = "4g",

    [string]$Image = "edge-voice-ptt-test:arm64"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ResultsDir = Join-Path $Root "results"
$ModelsDir = Join-Path $Root "models"

New-Item -ItemType Directory -Force -Path $ResultsDir, $ModelsDir | Out-Null

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

Invoke-Native {
    docker buildx build `
    --platform linux/arm64 `
    -t $Image `
    -f (Join-Path $Root "Dockerfile.arm64") `
    --load `
    $Root
}

$ResultsMount = "${ResultsDir}:/app/results"
$ModelsMount = "${ModelsDir}:/app/models:ro"

Invoke-Native {
    docker run --rm `
    --platform linux/arm64 `
    --memory $Memory `
    --memory-swap $Memory `
    --cpus 4 `
    -e PYTHONPATH=/app/src `
    -v $ResultsMount `
    -v $ModelsMount `
    $Image `
    python benchmarks/benchmark_pipeline.py --asr-backend simulated --tts-backend simulated --quant Q5 --threads 2 --duration 5 --loops 20 --out results/benchmark_sim.csv --redact-transcript
}
