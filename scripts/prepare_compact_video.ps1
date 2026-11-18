<#
.SYNOPSIS
Prepares an ingestion-ready compact media file while preserving audio fidelity.
Supports video files (MP4, MOV, MKV, WebM), audio-only files (M4A, MP3, WAV, FLAC, OGG),
common audio codecs (AAC, MP3, Opus, Vorbis, PCM), true-stereo vs. dual-mono detection,
and automatic lossless segmentation for long recordings.

.EXAMPLE
.\prepare_compact_video.ps1 -InputPath "C:\path\Panel.mp4"
.\prepare_compact_video.ps1 -Url "https://www.loom.com/share/..." -DownloadDir "C:\recordings" -OutputPath "C:\work\compact.mp4"
.\prepare_compact_video.ps1 -InputPath "C:\path\Interview.wav"
#>
param(
    [Parameter(Mandatory = $false)]
    [string]$InputPath,

    [string]$Url,

    [string]$OutputPath,

    [string]$DownloadDir,

    [int]$ConcurrentFragments = 8,

    [switch]$ScreenShare,

    [int]$Width = 480,

    [int]$Fps = 1,

    [int]$Crf = 35,

    [int]$SegmentSeconds = 1200,

    [double]$SegmentTriggerMinutes = 25,

    [double]$SegmentTriggerMB = 45
)

if (-not $InputPath -and -not $Url) {
    throw "Provide either -InputPath <file> or -Url <video_url>."
}

$EffectiveWidth = if ($ScreenShare) { [Math]::Max($Width, 960) } else { $Width }
$EffectiveCrf = if ($ScreenShare) { [Math]::Min($Crf, 28) } else { $Crf }

if ($Url -and -not $InputPath) {
    $dlDir = if ($DownloadDir) { $DownloadDir } elseif ($OutputPath) { Split-Path -Parent $OutputPath } else { (Get-Location).Path }
    if (-not $dlDir) { $dlDir = (Get-Location).Path }
    New-Item -ItemType Directory -Force -Path $dlDir | Out-Null

    $outTemplate = Join-Path $dlDir "%(title).80B_[%(id)s].%(ext)s"
    $ytFmt = if ($EffectiveWidth -le 480) {
        "bv*[height<=480]+ba[format_id!*=-drc]/b[height<=480]/bv*[height<=720]+ba[format_id!*=-drc]/b[height<=720]/bv*+ba[format_id!*=-drc]/b"
    } else {
        "bv*[height<=720]+ba[format_id!*=-drc]/b[height<=720]/bv*[height<=1080]+ba[format_id!*=-drc]/b[height<=1080]/bv*+ba[format_id!*=-drc]/b"
    }
    $fragCount = [Math]::Max(1, $ConcurrentFragments)
    $ytExe = Get-Command "yt-dlp" -ErrorAction SilentlyContinue
    $ytBaseArgs = @(
        "-f", $ytFmt,
        "--merge-output-format", "mp4",
        "--concurrent-fragments", "$fragCount",
        "--write-info-json",
        "--restrict-filenames",
        "-o", $outTemplate,
        "--print", "after_move:filepath",
        $Url
    )

    Write-Host "`nDownloading source video (non-DRC audio, adaptive height, concurrent fragments=$fragCount, info.json)..." -ForegroundColor Cyan
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if ($ytExe) {
        $dlOutput = & $ytExe.Source @ytBaseArgs 2>&1
    } else {
        $dlOutput = & python -m yt_dlp @ytBaseArgs 2>&1
    }
    $dlExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap

    if ($dlExit -ne 0) {
        $dlOutput | Out-String | Write-Host
        throw "yt-dlp failed with exit code $dlExit."
    }

    $downloadedPath = ($dlOutput | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Last 1)
    if (-not $downloadedPath) {
        throw "Download completed but output file path could not be resolved."
    }
    $InputPath = $downloadedPath
    Write-Host "Downloaded: $InputPath" -ForegroundColor Green
}

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InputPath)) {
    throw "Input file not found: $InputPath"
}

$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
$dir = Split-Path -Parent $resolvedInput
$base = [System.IO.Path]::GetFileNameWithoutExtension($resolvedInput)
$origMB = [math]::Round((Get-Item -LiteralPath $resolvedInput).Length / 1MB, 2)

function Get-ProbeField([string[]]$ProbeArgs) {
    $raw = (& ffprobe -v error @ProbeArgs "$resolvedInput" 2>$null | Out-String)
    return $raw.Trim()
}

Write-Host "Inspecting streams for: $resolvedInput ($origMB MB)" -ForegroundColor Cyan
& ffprobe -v error -show_entries format=duration,size -show_entries stream=index,codec_type,codec_name,bit_rate,channels,sample_rate,width,height -of default=noprint_wrappers=1 "$resolvedInput"

$videoStreams = Get-ProbeField @("-select_streams", "v", "-show_entries", "stream=index", "-of", "csv=p=0")
$hasVideo = -not [string]::IsNullOrWhiteSpace($videoStreams)

$audioCodec = (Get-ProbeField @("-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1")).ToLowerInvariant()
$channelsRaw = Get-ProbeField @("-select_streams", "a:0", "-show_entries", "stream=channels", "-of", "default=nw=1:nk=1")
$channels = if ($channelsRaw -match '^\d+$') { [int]$channelsRaw } else { 0 }

if ($channels -eq 0 -or [string]::IsNullOrWhiteSpace($audioCodec)) {
    throw "No audio stream found in: $resolvedInput"
}

if ($channels -eq 2) {
    Write-Host "`nChecking stereo channel difference (c0 - c1)..." -ForegroundColor Cyan
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $astatsOutput = (& ffmpeg -hide_banner -i "$resolvedInput" -af "pan=mono|c0=c0-c1,astats=measure_perchannel=0" -f null - 2>&1) | Out-String
    $ErrorActionPreference = $prevEap
    if ($astatsOutput -match "RMS level dB:\s*(-inf|[-\d\.]+)") {
        $rmsDiff = $Matches[1]
        $rmsVal = 0.0
        $isParsed = [double]::TryParse($rmsDiff, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$rmsVal)
        if ($rmsDiff -eq "-inf" -or ($isParsed -and $rmsVal -le -45.0)) {
            Write-Host "Channel topology: Dual-mono / negligible stereo separation (RMS diff = $rmsDiff dB). Safe to downmix to mono." -ForegroundColor Yellow
        } else {
            Write-Host "Channel topology: True stereo (RMS diff = $rmsDiff dB). Preserving spatial separation." -ForegroundColor Green
            Write-Host "Tip: Use -SplitChannels with extract_enhanced_clips.ps1 to isolate Left/Right speakers during crosstalk." -ForegroundColor Cyan
        }
    }
} elseif ($channels -eq 1) {
    Write-Host "`nChannel topology: Mono (1 channel)." -ForegroundColor Yellow
}

$compressedCodecs = @("aac", "mp3", "opus", "vorbis", "libopus", "libvorbis")

if (-not $hasVideo) {
    Write-Host "`nDetected audio-only input (codec: $audioCodec)." -ForegroundColor Cyan
    if ($compressedCodecs -contains $audioCodec -and $origMB -lt 90) {
        if (-not $OutputPath) {
            $OutputPath = $resolvedInput
            Write-Host "Audio is already compressed ($audioCodec) and under 90 MB ($origMB MB). Keep as-is." -ForegroundColor Green
        } else {
            Copy-Item -LiteralPath $resolvedInput -Destination $OutputPath -Force
            Write-Host "Copied compact audio directly without re-encoding -> $OutputPath ($origMB MB)" -ForegroundColor Green
        }
    } else {
        if (-not $OutputPath) {
            $OutputPath = Join-Path $dir "${base}_compact.m4a"
        }
        Write-Host "Encoding audio ($audioCodec, $origMB MB) to high-bitrate 128k AAC -> $OutputPath" -ForegroundColor Cyan
        & ffmpeg -y -i "$resolvedInput" -vn -c:a aac -b:a 128k "$OutputPath" -loglevel error
        if ($LASTEXITCODE -ne 0) { throw "ffmpeg audio compaction failed with exit code $LASTEXITCODE" }
    }
} else {
    $mp4CopyCodecs = @("aac", "mp3")
    $mkvCopyCodecs = @("opus", "vorbis", "libopus", "libvorbis")

    if ($mp4CopyCodecs -contains $audioCodec) {
        $defaultExt = ".mp4"
        $audioArgs = @("-c:a", "copy")
        $audioMode = "lossless bitstream copy (-c:a copy)"
    } elseif ($mkvCopyCodecs -contains $audioCodec) {
        if ($OutputPath -and [System.IO.Path]::GetExtension($OutputPath).ToLowerInvariant() -eq ".mp4") {
            Write-Warning "Audio codec '$audioCodec' cannot be safely muxed into .mp4 with -c:a copy. Transcoding at high-bitrate 128k AAC (omit -OutputPath to keep -c:a copy in .mkv)."
            $defaultExt = ".mp4"
            $audioArgs = @("-c:a", "aac", "-b:a", "128k")
            $audioMode = "high-bitrate 128k AAC transcode"
        } else {
            $defaultExt = ".mkv"
            $audioArgs = @("-c:a", "copy")
            $audioMode = "lossless bitstream copy into .mkv (-c:a copy)"
        }
    } else {
        Write-Warning "Uncompressed/lossless audio codec '$audioCodec' detected. Encoding at high-bitrate 128k AAC to stay under ingestion size limits."
        $defaultExt = ".mp4"
        $audioArgs = @("-c:a", "aac", "-b:a", "128k")
        $audioMode = "high-bitrate 128k AAC transcode"
    }

    if (-not $OutputPath) {
        $OutputPath = Join-Path $dir "${base}_compact_${Fps}fps${defaultExt}"
    }

    $gopFrames = [Math]::Max(1, $Fps * 10)
    Write-Host "`nCreating ${Fps} FPS video (max ${EffectiveWidth}px wide, no upscale, CRF $EffectiveCrf, keyint ${gopFrames}) with $audioMode..." -ForegroundColor Cyan
    & ffmpeg -y -i "$resolvedInput" -vf "scale=trunc(min($EffectiveWidth\,iw)/2)*2:-2,fps=${Fps}" -c:v libx264 -g $gopFrames -crf $EffectiveCrf -preset veryfast @audioArgs "$OutputPath" -loglevel error
    if ($LASTEXITCODE -ne 0) {
        throw "ffmpeg compaction failed with exit code $LASTEXITCODE"
    }
}

$newMB = [math]::Round((Get-Item -LiteralPath $OutputPath).Length / 1MB, 2)
Write-Host "`nCompaction summary:" -ForegroundColor Green
Write-Host "Original size : $origMB MB"
Write-Host "Compact size  : $newMB MB"
Write-Host "Output path   : $OutputPath"

$outDurationSec = 0.0
$durProbe = (& ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$OutputPath" 2>$null)
[void][double]::TryParse(($durProbe | Out-String).Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$outDurationSec)
$outDurationMin = [Math]::Round($outDurationSec / 60.0, 2)

if ($SegmentSeconds -gt 0 -and (($newMB -gt $SegmentTriggerMB) -or ($outDurationMin -gt $SegmentTriggerMinutes))) {
    Write-Host "`nOutput ($newMB MB, ${outDurationMin} min) exceeds compaction-safe threshold (${SegmentTriggerMB} MB / ${SegmentTriggerMinutes} min). Splitting into ${SegmentSeconds}s lossless segments for ingestion..." -ForegroundColor Yellow
    $segDir = Split-Path -Parent $OutputPath
    $segBase = [System.IO.Path]::GetFileNameWithoutExtension($OutputPath)
    $segExt = [System.IO.Path]::GetExtension($OutputPath)
    $segPattern = Join-Path $segDir "${segBase}_part%02d${segExt}"

    & ffmpeg -y -i "$OutputPath" -f segment -segment_time $SegmentSeconds -reset_timestamps 1 -c copy "$segPattern" -loglevel error
    if ($LASTEXITCODE -ne 0) {
        throw "ffmpeg segmentation failed with exit code $LASTEXITCODE"
    }

    Get-ChildItem -LiteralPath $segDir -Filter "${segBase}_part*${segExt}" | Sort-Object Name | ForEach-Object {
        $partMB = [math]::Round($_.Length / 1MB, 2)
        Write-Host ("  Segment: {0} ({1} MB)" -f $_.FullName, $partMB)
    }
}
