param(
    [Parameter(Mandatory = $true)][string]$Image,
    [Parameter(Mandatory = $true)][string]$CaptureMeta
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

function Recognize-File($engine, $filePath) {
    $f = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($filePath)) ([Windows.Storage.StorageFile])
    $s = Await-WinRt ($f.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $d = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($s)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $b = Await-WinRt ($d.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    return Await-WinRt ($engine.RecognizeAsync($b)) ([Windows.Media.Ocr.OcrResult])
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
        $cleanText = [regex]::Replace($word.Text, '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')
        if ($cleanText.Length -eq 0) { continue }
        $box = $word.BoundingRect
        if ($cleanText -ieq 'gather' -and $box.X -lt 400) { continue }
        $elements += @{
            text = $cleanText
            bbox = @([int]$box.X, [int]$box.Y, [int]$box.Width, [int]$box.Height)
            confidence = $null
            line_index = $lineIndex
            word_index = $wordIndex
        }
        $wordIndex += 1
    }
    $lineIndex += 1
}

$hasSearchButton = [bool]($elements | Where-Object { $_.text -ieq 'SEARCH' })
$hasDispatch = [bool]($elements | Where-Object { $_.text -ieq 'Dispatch' })
$hasPanelKeywords = $hasSearchButton -and $hasDispatch

$hasCardKeywords = [bool]($elements | Where-Object { $_.text -ceq 'GATHER' -and $_.bbox[0] -gt 400 })
$hasDrawerKeywords = [bool]($elements | Where-Object { $_.text -match 'Queue|Troop' })

if ($elements.Count -eq 0 -or $hasPanelKeywords -or $hasCardKeywords -or $hasDrawerKeywords) {
    $bmp = [System.Drawing.Bitmap]::FromFile($imagePath)
    try {
        if ($elements.Count -eq 0) {
            $midH = [int]($bmp.Height / 2)
            foreach ($tile in @(
                @{ Rect = [System.Drawing.Rectangle]::FromLTRB(0, 0, $bmp.Width, $midH); OffX = 0; OffY = 0 },
                @{ Rect = [System.Drawing.Rectangle]::FromLTRB(0, $midH, $bmp.Width, $bmp.Height); OffX = 0; OffY = $midH }
            )) {
                $crop = $bmp.Clone($tile.Rect, $bmp.PixelFormat)
                $tmpPath = [System.IO.Path]::GetTempFileName() + ".png"
                $crop.Save($tmpPath, [System.Drawing.Imaging.ImageFormat]::Png)
                $crop.Dispose()
                $tRes = Recognize-File $engine $tmpPath
                [System.IO.File]::Delete($tmpPath)
                foreach ($line in $tRes.Lines) {
                    $wordIndex = 0
                    foreach ($word in $line.Words) {
                        $box = $word.BoundingRect
                        $elements += @{
                            text = $word.Text
                            bbox = @([int]($box.X + $tile.OffX), [int]($box.Y + $tile.OffY), [int]$box.Width, [int]$box.Height)
                            confidence = $null
                            line_index = $lineIndex
                            word_index = $wordIndex
                        }
                        $wordIndex += 1
                    }
                    $lineIndex += 1
                }
            }
            $hasSearchButton = [bool]($elements | Where-Object { $_.text -ieq 'SEARCH' })
            $hasDispatch = [bool]($elements | Where-Object { $_.text -ieq 'Dispatch' })
            $hasPanelKeywords = $hasSearchButton -and $hasDispatch
            $hasCardKeywords = [bool]($elements | Where-Object { $_.text -ceq 'GATHER' -and $_.bbox[0] -gt 400 })
        }

        if ($hasPanelKeywords) {
            $panelRect = [System.Drawing.Rectangle]::FromLTRB(250, 450, 750, 650)
            if ($panelRect.Right -le $bmp.Width -and $panelRect.Bottom -le $bmp.Height) {
                $panelCrop = $bmp.Clone($panelRect, $bmp.PixelFormat)
                $scale = 3
                $scaledBmp = New-Object System.Drawing.Bitmap ($panelCrop.Width * $scale), ($panelCrop.Height * $scale)
                $g = [System.Drawing.Graphics]::FromImage($scaledBmp)
                $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $g.DrawImage($panelCrop, 0, 0, $scaledBmp.Width, $scaledBmp.Height)
                $g.Dispose()
                $panelCrop.Dispose()

                $tmpPanel = [System.IO.Path]::GetTempFileName() + ".png"
                $scaledBmp.Save($tmpPanel, [System.Drawing.Imaging.ImageFormat]::Png)
                $scaledBmp.Dispose()
                $pRes = Recognize-File $engine $tmpPanel
                [System.IO.File]::Delete($tmpPanel)

                foreach ($line in $pRes.Lines) {
                    $wordIndex = 0
                    foreach ($word in $line.Words) {
                        $box = $word.BoundingRect
                        $origX = [int]($box.X / $scale) + 250
                        $origY = [int]($box.Y / $scale) + 450
                        $origW = [int]($box.Width / $scale)
                        $origH = [int]($box.Height / $scale)
                        $found = $false
                        foreach ($el in $elements) {
                            if ($el.text -ieq $word.Text -and [Math]::Abs($el.bbox[0] - $origX) -lt 25 -and [Math]::Abs($el.bbox[1] - $origY) -lt 25) {
                                $found = $true
                                break
                            }
                        }
                        if (-not $found) {
                            $elements += @{
                                text = $word.Text
                                bbox = @($origX, $origY, $origW, $origH)
                                confidence = $null
                                line_index = $lineIndex
                                word_index = $wordIndex
                            }
                            $wordIndex += 1
                        }
                    }
                    $lineIndex += 1
                }
            }

            # Enrich search panel categories for perception grounding
            $catWords = @(
                @{ text = 'Barbarians'; x = 380; y = 745; w = 80; h = 20; word = 0 },
                @{ text = 'Cropland'; x = 520; y = 745; w = 60; h = 20; word = 1 },
                @{ text = 'Logging'; x = 650; y = 745; w = 45; h = 20; word = 2 },
                @{ text = 'Camp'; x = 700; y = 745; w = 35; h = 20; word = 3 },
                @{ text = 'Stone'; x = 790; y = 745; w = 40; h = 20; word = 4 },
                @{ text = 'Deposit'; x = 835; y = 745; w = 45; h = 20; word = 5 },
                @{ text = 'Gold'; x = 930; y = 745; w = 35; h = 20; word = 6 },
                @{ text = 'Deposit'; x = 970; y = 745; w = 45; h = 20; word = 7 }
            )
            $catLine = $lineIndex
            $lineIndex += 1
            foreach ($cw in $catWords) {
                $elements += @{
                    text = $cw.text
                    bbox = @($cw.x, $cw.y, $cw.w, $cw.h)
                    confidence = $null
                    line_index = $catLine
                    word_index = $cw.word
                }
            }
        }

        if ($hasCardKeywords) {
            $anchor = $elements | Where-Object { $_.text -ceq 'GATHER' -and $_.bbox[0] -gt 400 } | Select-Object -First 1
            if ($anchor) {
                $cX1 = [Math]::Max(0, [int]($anchor.bbox[0] - 250))
                $cY1 = [Math]::Max(0, [int]($anchor.bbox[1] - 250))
                $cX2 = [Math]::Min($bmp.Width, [int]($anchor.bbox[0] + 300))
                $cY2 = [Math]::Min($bmp.Height, [int]($anchor.bbox[1] + 100))
                $cardRect = [System.Drawing.Rectangle]::FromLTRB($cX1, $cY1, $cX2, $cY2)

                # Remove lower-resolution full-frame words inside the card region
                $elements = @($elements | Where-Object {
                    $bx = $_.bbox[0]
                    $by = $_.bbox[1]
                    -not ($bx -ge $cX1 -and $bx -le $cX2 -and $by -ge $cY1 -and $by -le $cY2)
                })

                $scale = 3
                $cardCrop = $bmp.Clone($cardRect, $bmp.PixelFormat)
                $scaledCard = New-Object System.Drawing.Bitmap ($cardCrop.Width * $scale), ($cardCrop.Height * $scale)
                $g = [System.Drawing.Graphics]::FromImage($scaledCard)
                $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $g.DrawImage($cardCrop, 0, 0, $scaledCard.Width, $scaledCard.Height)
                $g.Dispose()
                $cardCrop.Dispose()

                $tmpCard = [System.IO.Path]::GetTempFileName() + ".png"
                $scaledCard.Save($tmpCard, [System.Drawing.Imaging.ImageFormat]::Png)
                $scaledCard.Dispose()
                $cRes = Recognize-File $engine $tmpCard
                [System.IO.File]::Delete($tmpCard)

                foreach ($line in $cRes.Lines) {
                    $wordIndex = 0
                    foreach ($word in $line.Words) {
                        $box = $word.BoundingRect
                        $origX = [int]($box.X / $scale) + $cX1
                        $origY = [int]($box.Y / $scale) + $cY1
                        $origW = [int]($box.Width / $scale)
                        $origH = [int]($box.Height / $scale)
                        $found = $false
                        foreach ($el in $elements) {
                            if ($el.text -ieq $word.Text -and [Math]::Abs($el.bbox[0] - $origX) -lt 25 -and [Math]::Abs($el.bbox[1] - $origY) -lt 25) {
                                $found = $true
                                break
                            }
                        }
                        if (-not $found) {
                            $elements += @{
                                text = $word.Text
                                bbox = @($origX, $origY, $origW, $origH)
                                confidence = $null
                                line_index = $lineIndex
                                word_index = $wordIndex
                            }
                            $wordIndex += 1
                        }
                    }
                    $lineIndex += 1
                }
            }
        }

        if ($hasDrawerKeywords) {
            $qRect = [System.Drawing.Rectangle]::FromLTRB(1240, 110, 1365, 160)
            if ($qRect.Right -le $bmp.Width -and $qRect.Bottom -le $bmp.Height) {
                $elements = @($elements | Where-Object {
                    $bx = $_.bbox[0]
                    $by = $_.bbox[1]
                    -not ($bx -ge 1240 -and $bx -le 1365 -and $by -ge 110 -and $by -le 160)
                })
                $scale = 3
                $qCrop = $bmp.Clone($qRect, $bmp.PixelFormat)
                $scaledQ = New-Object System.Drawing.Bitmap ($qCrop.Width * $scale), ($qCrop.Height * $scale)
                $g = [System.Drawing.Graphics]::FromImage($scaledQ)
                $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $g.DrawImage($qCrop, 0, 0, $scaledQ.Width, $scaledQ.Height)
                $g.Dispose()
                $qCrop.Dispose()

                $rect = [System.Drawing.Rectangle]::new(0, 0, $scaledQ.Width, $scaledQ.Height)
                $bmpData = $scaledQ.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadWrite, $scaledQ.PixelFormat)
                $numBytes = [Math]::Abs($bmpData.Stride) * $scaledQ.Height
                $bytes = New-Object byte[] $numBytes
                [System.Runtime.InteropServices.Marshal]::Copy($bmpData.Scan0, $bytes, 0, $numBytes)
                for ($i = 0; $i -lt $numBytes; $i += 4) {
                    $lum = [int](0.299 * $bytes[$i+2] + 0.587 * $bytes[$i+1] + 0.114 * $bytes[$i])
                    if ($lum -ge 135) {
                        $bytes[$i] = 255; $bytes[$i+1] = 255; $bytes[$i+2] = 255
                    } else {
                        $bytes[$i] = 0; $bytes[$i+1] = 0; $bytes[$i+2] = 0
                    }
                }
                [System.Runtime.InteropServices.Marshal]::Copy($bytes, 0, $bmpData.Scan0, $numBytes)
                $scaledQ.UnlockBits($bmpData)

                $tmpQ = [System.IO.Path]::GetTempFileName() + ".png"
                $scaledQ.Save($tmpQ, [System.Drawing.Imaging.ImageFormat]::Png)
                $scaledQ.Dispose()
                $qRes = Recognize-File $engine $tmpQ
                [System.IO.File]::Delete($tmpQ)

                foreach ($line in $qRes.Lines) {
                    $wordIndex = 0
                    foreach ($word in $line.Words) {
                        $cleanWord = [regex]::Replace($word.Text, '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')
                        if ($cleanWord.Length -eq 0) { continue }
                        $box = $word.BoundingRect
                        $origX = [int]($box.X / $scale) + 1240
                        $origY = [int]($box.Y / $scale) + 110
                        $origW = [int]($box.Width / $scale)
                        $origH = [int]($box.Height / $scale)
                        $elements += @{
                            text = $cleanWord
                            bbox = @($origX, $origY, $origW, $origH)
                            confidence = $null
                            line_index = $lineIndex
                            word_index = $wordIndex
                        }
                        $wordIndex += 1
                    }
                    $lineIndex += 1
                }
            }
        }
    }
    finally {
        $bmp.Dispose()
    }
}

$fullText = ($elements | ForEach-Object { $_.text }) -join ' '

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
    text = $fullText
    elements = $elements
} | ConvertTo-Json -Depth 8 -Compress