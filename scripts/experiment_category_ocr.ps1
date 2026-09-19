param(
    [Parameter(Mandatory = $true)][string]$Image,
    [string]$Output = ""
)
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

function Recognize-File($engine, [string]$FilePath) {
    $file = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($FilePath)) ([Windows.Storage.StorageFile])
    $stream = Await-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    return Await-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
}

$imagePath = (Resolve-Path -LiteralPath $Image).Path
$bmp = [System.Drawing.Bitmap]::new($imagePath)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'Windows.Media.Ocr has no user-profile language engine' }

# Fixed client-relative label ROIs are processing windows only.  They are not
# action coordinates and this script never opens or activates the game.
$labels = @(
    @{ id = 'Barbarians'; rect = [System.Drawing.Rectangle]::new(350, 732, 105, 24) },
    @{ id = 'Cropland'; rect = [System.Drawing.Rectangle]::new(500, 732, 105, 24) },
    @{ id = 'Logging Camp'; rect = [System.Drawing.Rectangle]::new(625, 732, 125, 24) },
    @{ id = 'Stone Deposit'; rect = [System.Drawing.Rectangle]::new(770, 732, 135, 24) },
    @{ id = 'Gold Deposit'; rect = [System.Drawing.Rectangle]::new(915, 732, 140, 24) }
)
$scales = @(8, 12, 16)
$interpolations = @(
    [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor,
    [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic,
    [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBilinear
)
$results = @()
foreach ($label in $labels) {
    foreach ($scale in $scales) {
        foreach ($interpolation in $interpolations) {
            $rect = $label.rect
            if ($rect.Right -gt $bmp.Width -or $rect.Bottom -gt $bmp.Height) { continue }
            $crop = $bmp.Clone($rect, $bmp.PixelFormat)
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
                    scale = $scale
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
