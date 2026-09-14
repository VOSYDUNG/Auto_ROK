param(
    [Parameter(Mandatory = $true)][string]$Image,
    [Parameter(Mandatory = $true)][string]$CaptureMeta
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
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

$imagePath = (Resolve-Path -LiteralPath $Image).Path
$capturePath = (Resolve-Path -LiteralPath $CaptureMeta).Path
$capture = Get-Content -Raw -LiteralPath $capturePath | ConvertFrom-Json
if ($capture.status -ne 'captured' -or $capture.target.title -ne 'Rise of Kingdoms' -or $capture.target.exe -ne 'MASS.exe') {
    throw 'capture metadata is not successful Rise of Kingdoms/MASS.exe evidence'
}
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$imageStream = [System.IO.File]::OpenRead($imagePath)
try {
    $actualHash = ([System.BitConverter]::ToString($sha256.ComputeHash($imageStream))).Replace('-', '').ToLowerInvariant()
}
finally {
    $imageStream.Dispose()
    $sha256.Dispose()
}
if ($actualHash -ne $capture.frame.image_sha256) { throw 'image hash does not match capture metadata' }

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'Windows.Media.Ocr has no user-profile language engine' }
$file = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imagePath)) ([Windows.Storage.StorageFile])
$stream = Await-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
if ($bitmap.PixelWidth -ne $capture.frame.width -or $bitmap.PixelHeight -ne $capture.frame.height) {
    throw 'decoded image dimensions do not match capture client bounds'
}
$result = Await-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$elements = @()
$lineIndex = 0
foreach ($line in $result.Lines) {
    $wordIndex = 0
    foreach ($word in $line.Words) {
        $box = $word.BoundingRect
        $elements += @{
            text = $word.Text
            bbox = @([int]$box.X, [int]$box.Y, [int]$box.Width, [int]$box.Height)
            confidence = $null
            line_index = $lineIndex
            word_index = $wordIndex
        }
        $wordIndex += 1
    }
    $lineIndex += 1
}
@{
    schema_version = 1
    frame_id = $capture.frame.id
    image_sha256 = $actualHash
    coordinate_space = 'ocr_crop_pixels'
    output_coordinate_space = 'client_pixels'
    client_bounds = @($capture.frame.client_bounds)
    dpi_scale = $capture.frame.dpi_scale
    backend = @{
        name = 'Windows.Media.Ocr'
        version = [Environment]::OSVersion.Version.ToString()
        language = $engine.RecognizerLanguage.LanguageTag
    }
    crop = @(0, 0, [int]$bitmap.PixelWidth, [int]$bitmap.PixelHeight)
    scale_x = 1.0
    scale_y = 1.0
    text = $result.Text
    elements = $elements
} | ConvertTo-Json -Depth 8 -Compress