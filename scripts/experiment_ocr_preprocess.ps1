param(
    [Parameter(Mandatory = $true)][string]$Image,
    [string]$Output = ""
)

# Diagnostic only.  This script reads a persisted image, emits no input and
# never changes the runtime OCR/grounding path.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing
[void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
[void][Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]

function Await-WinRt($Operation, [Type]$ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } |
        Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

function Recognize-File($Engine, [string]$FilePath) {
    $file = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($FilePath)) ([Windows.Storage.StorageFile])
    $stream = Await-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    return Await-WinRt ($Engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
}

function Convert-Pixel([System.Drawing.Color]$Color, [string]$Variant) {
    $lum = [int](0.299 * $Color.R + 0.587 * $Color.G + 0.114 * $Color.B)
    if ($Variant -eq 'gray') {
        return [System.Drawing.Color]::FromArgb(255, $lum, $lum, $lum)
    }
    if ($Variant -eq 'threshold120') {
        $v = if ($lum -ge 120) { 255 } else { 0 }
        return [System.Drawing.Color]::FromArgb(255, $v, $v, $v)
    }
    if ($Variant -eq 'threshold160') {
        $v = if ($lum -ge 160) { 255 } else { 0 }
        return [System.Drawing.Color]::FromArgb(255, $v, $v, $v)
    }
    if ($Variant -eq 'bright_text') {
        $keep = ($lum -ge 120) -or ($Color.R -ge 150 -and $Color.G -ge 110 -and $Color.B -le 130)
        $v = if ($keep) { 255 } else { 0 }
        return [System.Drawing.Color]::FromArgb(255, $v, $v, $v)
    }
    return $Color
}

$imagePath = (Resolve-Path -LiteralPath $Image).Path
$bmp = [System.Drawing.Bitmap]::new($imagePath)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'Windows.Media.Ocr has no user-profile language engine' }

$labels = @(
    @{ id = 'Barbarians'; rect = [System.Drawing.Rectangle]::new(350, 732, 105, 24) },
    @{ id = 'Cropland'; rect = [System.Drawing.Rectangle]::new(500, 732, 105, 24) },
    @{ id = 'Logging Camp'; rect = [System.Drawing.Rectangle]::new(625, 732, 125, 24) },
    @{ id = 'Stone Deposit'; rect = [System.Drawing.Rectangle]::new(770, 732, 135, 24) },
    @{ id = 'Gold Deposit'; rect = [System.Drawing.Rectangle]::new(915, 732, 140, 24) }
)
$variants = @('raw', 'gray', 'threshold120', 'threshold160', 'bright_text')
$interpolations = @(
    [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic,
    [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
)
$results = @()
foreach ($label in $labels) {
    foreach ($variant in $variants) {
        foreach ($interpolation in $interpolations) {
            $rect = $label.rect
            if ($rect.Right -gt $bmp.Width -or $rect.Bottom -gt $bmp.Height) { continue }
            $crop = $bmp.Clone($rect, $bmp.PixelFormat)
            if ($variant -ne 'raw') {
                for ($y = 0; $y -lt $crop.Height; $y++) {
                    for ($x = 0; $x -lt $crop.Width; $x++) {
                        $crop.SetPixel($x, $y, (Convert-Pixel $crop.GetPixel($x, $y) $variant))
                    }
                }
            }
            $scale = 12
            $scaled = [System.Drawing.Bitmap]::new($crop.Width * $scale, $crop.Height * $scale)
            $graphics = [System.Drawing.Graphics]::FromImage($scaled)
            $graphics.InterpolationMode = $interpolation
            $graphics.DrawImage($crop, 0, 0, $scaled.Width, $scaled.Height)
            $graphics.Dispose()
            $crop.Dispose()
            $temp = [System.IO.Path]::GetTempFileName() + '.png'
            $scaled.Save($temp, [System.Drawing.Imaging.ImageFormat]::Png)
            $scaled.Dispose()
            try {
                $ocr = Recognize-File $engine $temp
                $text = (($ocr.Lines | ForEach-Object { $_.Text }) -join ' ').Trim()
                $results += [ordered]@{
                    label = $label.id
                    variant = $variant
                    interpolation = $interpolation.ToString()
                    text = $text
                }
            }
            finally {
                [System.IO.File]::Delete($temp)
            }
        }
    }
}
$bmp.Dispose()
$report = [ordered]@{
    schema_version = 1
    status = 'experiment_only'
    image = $imagePath
    processing_device = 'cpu'
    input_emitted = $false
    results = $results
}
$json = $report | ConvertTo-Json -Depth 8
if ($Output) {
    $outPath = [System.IO.Path]::GetFullPath($Output)
    $parent = [System.IO.Path]::GetDirectoryName($outPath)
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    [System.IO.File]::WriteAllText($outPath, $json + [Environment]::NewLine, [Text.Encoding]::UTF8)
}
$json
