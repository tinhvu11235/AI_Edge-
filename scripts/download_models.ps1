param(
    [string]$WhisperModel = "tiny"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WhisperDir = Join-Path $Root "models\whisper"
$PiperDir = Join-Path $Root "models\piper\vi_VN-vais1000-medium"

New-Item -ItemType Directory -Force -Path $WhisperDir, $PiperDir | Out-Null

function Get-ModelFile {
    param(
        [string]$Url,
        [string]$OutFile
    )

    $PartFile = "$OutFile.part"

    if (Test-Path -LiteralPath $OutFile) {
        $existing = Get-Item -LiteralPath $OutFile
        if ($existing.Length -gt 0) {
            Write-Host "Already exists: $OutFile"
            return
        }
    }

    if (Test-Path -LiteralPath $PartFile) {
        Remove-Item -LiteralPath $PartFile -Force
    }

    Write-Host "Downloading $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $PartFile
    Move-Item -LiteralPath $PartFile -Destination $OutFile -Force
}

$WhisperOut = Join-Path $WhisperDir "ggml-$WhisperModel.bin"
Get-ModelFile `
    -Url "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$WhisperModel.bin" `
    -OutFile $WhisperOut

Get-ModelFile `
    -Url "https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx" `
    -OutFile (Join-Path $PiperDir "vi_VN-vais1000-medium.onnx")

Get-ModelFile `
    -Url "https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx.json" `
    -OutFile (Join-Path $PiperDir "vi_VN-vais1000-medium.onnx.json")

$HashFile = Join-Path $Root "models\SHA256SUMS.txt"
Get-ChildItem -LiteralPath (Join-Path $Root "models") -Recurse -File |
    Sort-Object FullName |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash)  $($_.Path.Substring($Root.Length + 1))" } |
    Set-Content -Encoding ASCII -Path $HashFile

Write-Host "Wrote $HashFile"
