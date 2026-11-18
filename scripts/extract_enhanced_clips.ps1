<#
.SYNOPSIS
Extracts targeted low-SNR windows from a media file as uncompressed 16-bit PCM .wav clips
with a speech band-pass filter (100 Hz - 8 kHz) and dynamic audio normalization.
Supports optional stereo Left/Right channel isolation (-SplitChannels) for overlapping speech.

.EXAMPLE
.\extract_enhanced_clips.ps1 -InputPath "C:\path\Panel.mp4" -OutputDir "C:\scratch" -Windows @("00:01:40-00:02:20", "00:28:30-00:29:05")
.\extract_enhanced_clips.ps1 -InputPath "C:\path\StereoPanel.mp4" -OutputDir "C:\scratch" -Windows @("00:10:00-00:10:30") -SplitChannels
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [string]$OutputDir = (Get-Location).Path,

    [Parameter(Mandatory = $true)]
    [string[]]$Windows,

    [switch]$SplitChannels
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InputPath)) {
    throw "Input file not found: $InputPath"
}

if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
$baseFilter = "highpass=f=100,lowpass=f=8000,dynaudnorm=f=150:g=15"

if ($SplitChannels) {
    $channelsRaw = (& ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=nw=1:nk=1 "$resolvedInput" 2>$null | Out-String).Trim()
    $channels = if ($channelsRaw -match '^\d+$') { [int]$channelsRaw } else { 0 }
    if ($channels -lt 2) {
        Write-Warning "-SplitChannels requested, but input has $channels audio channel(s). Extracting single mixed clips instead."
        $SplitChannels = $false
    }
}

function Invoke-ClipExtract([string]$Start, [string]$End, [string]$Filter, [string]$OutFile) {
    & ffmpeg -y -ss $Start -to $End -i "$resolvedInput" -af $Filter -c:a pcm_s16le "$OutFile" -loglevel error
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutFile)) {
        throw "Failed to extract clip ($Start -> $End) to $OutFile"
    }
    Write-Host ("Created: {0} ({1} -> {2})" -f $OutFile, $Start, $End)
}

$existingIndices = @(
    Get-ChildItem -LiteralPath $OutputDir -Filter "w*.wav" -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match '^w(\d+)_') { [int]$Matches[1] }
    }
)
$idx = if ($existingIndices.Count -gt 0) { (($existingIndices | Measure-Object -Maximum).Maximum) + 1 } else { 1 }
foreach ($win in $Windows) {
    $parts = $win.Split('-')
    if ($parts.Count -ne 2) {
        throw "Invalid window format '$win'. Expected 'HH:MM:SS-HH:MM:SS' or 'MM:SS-MM:SS'."
    }
    $start = $parts[0].Trim()
    $end = $parts[1].Trim()

    # Normalize MM:SS to 00:MM:SS for ffmpeg
    if ($start -match '^\d{1,2}:\d{2}(\.\d+)?$') { $start = "00:$start" }
    if ($end -match '^\d{1,2}:\d{2}(\.\d+)?$') { $end = "00:$end" }

    $tagStart = ($start -replace '[:\.]', '')
    $tagEnd = ($end -replace '[:\.]', '')
    $stem = ("w{0:D2}_{1}_{2}" -f $idx, $tagStart, $tagEnd)

    if ($SplitChannels) {
        Invoke-ClipExtract $start $end "pan=mono|c0=c0,$baseFilter" (Join-Path $OutputDir "${stem}_L.wav")
        Invoke-ClipExtract $start $end "pan=mono|c0=c1,$baseFilter" (Join-Path $OutputDir "${stem}_R.wav")
    } else {
        Invoke-ClipExtract $start $end $baseFilter (Join-Path $OutputDir "${stem}.wav")
    }
    $idx++
}
