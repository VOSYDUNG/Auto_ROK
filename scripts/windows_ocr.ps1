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

# Windows.Media.Ocr can miss the fixed SEARCH/Dispatch labels on the
# 1366x768 client even when the search drawer is visibly open.  Use two
# independent words inside the compiled panel bounds as a conservative
# surface anchor, then run the same bounded panel crop/enrichment path.  This
# is still observation-only; it does not infer a resource choice or arm input.
$hasSearchPanelAnchor = [bool](
    ($elements | Where-Object {
        $_.text -ieq 'Barbarians' -and
        $_.bbox[0] -ge 250 -and $_.bbox[0] -le 600 -and
        $_.bbox[1] -ge 350 -and $_.bbox[1] -le 520
    }) -and
    ($elements | Where-Object {
        $_.text -match '^Level:?$' -and
        $_.bbox[0] -ge 250 -and $_.bbox[0] -le 600 -and
        $_.bbox[1] -ge 430 -and $_.bbox[1] -le 560
    })
)
$hasSearchPanelSurface = $hasPanelKeywords -or $hasSearchPanelAnchor

$hasCardKeywords = [bool]($elements | Where-Object { $_.text -ceq 'GATHER' -and $_.bbox[0] -gt 400 })
$hasDrawerKeywords = [bool]($elements | Where-Object { $_.text -match 'Queue|Troop' })
$hasNewTroopSetupKeywords = [bool](
    ($elements | Where-Object { $_.text -ieq 'New' }) -and
    ($elements | Where-Object { $_.text -ieq 'Troop' }) -and
    ($elements | Where-Object { $_.text -ieq 'MARCH' })
)

if ($elements.Count -eq 0 -or $hasSearchPanelSurface -or $hasCardKeywords -or $hasDrawerKeywords -or $hasNewTroopSetupKeywords) {
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
            $hasSearchPanelAnchor = [bool](
                ($elements | Where-Object {
                    $_.text -ieq 'Barbarians' -and
                    $_.bbox[0] -ge 250 -and $_.bbox[0] -le 600 -and
                    $_.bbox[1] -ge 350 -and $_.bbox[1] -le 520
                }) -and
                ($elements | Where-Object {
                    $_.text -match '^Level:?$' -and
                    $_.bbox[0] -ge 250 -and $_.bbox[0] -le 600 -and
                    $_.bbox[1] -ge 430 -and $_.bbox[1] -le 560
                })
            )
            $hasSearchPanelSurface = $hasPanelKeywords -or $hasSearchPanelAnchor
            $hasCardKeywords = [bool]($elements | Where-Object { $_.text -ceq 'GATHER' -and $_.bbox[0] -gt 400 })
        }

        if ($hasNewTroopSetupKeywords) {
            # The small ``Units`` label on the fixed New Troop modal is a
            # known Windows.Media.Ocr holdout at native 1366x768 scale.  A
            # bounded enlarged crop makes the label available as current-frame
            # OCR evidence without compiling a semantic state or a click point.
            # The crop is intentionally limited to the lower modal summary;
            # every returned box is mapped back into client pixels.
            $troopSummaryRect = [System.Drawing.Rectangle]::FromLTRB(600, 450, 1035, 635)
            if ($troopSummaryRect.Right -le $bmp.Width -and $troopSummaryRect.Bottom -le $bmp.Height) {
                $troopSummaryScale = 4
                $troopSummaryCrop = $bmp.Clone($troopSummaryRect, $bmp.PixelFormat)
                $scaledTroopSummary = New-Object System.Drawing.Bitmap ($troopSummaryCrop.Width * $troopSummaryScale), ($troopSummaryCrop.Height * $troopSummaryScale)
                $g = [System.Drawing.Graphics]::FromImage($scaledTroopSummary)
                $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $g.DrawImage($troopSummaryCrop, 0, 0, $scaledTroopSummary.Width, $scaledTroopSummary.Height)
                $g.Dispose()
                $troopSummaryCrop.Dispose()

                $tmpTroopSummary = [System.IO.Path]::GetTempFileName() + ".png"
                $scaledTroopSummary.Save($tmpTroopSummary, [System.Drawing.Imaging.ImageFormat]::Png)
                $scaledTroopSummary.Dispose()
                $troopSummaryRes = Recognize-File $engine $tmpTroopSummary
                [System.IO.File]::Delete($tmpTroopSummary)

                foreach ($line in $troopSummaryRes.Lines) {
                    $wordIndex = 0
                    foreach ($word in $line.Words) {
                        $cleanWord = [regex]::Replace($word.Text, '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')
                        if ($cleanWord.Length -eq 0) { continue }
                        $box = $word.BoundingRect
                        $origX = [int]($box.X / $troopSummaryScale) + 600
                        $origY = [int]($box.Y / $troopSummaryScale) + 450
                        $origW = [int]($box.Width / $troopSummaryScale)
                        $origH = [int]($box.Height / $troopSummaryScale)
                        $duplicate = $false
                        foreach ($el in $elements) {
                            if ($el.text -ieq $cleanWord -and
                                [Math]::Abs([int]$el.bbox[0] - $origX) -lt 25 -and
                                [Math]::Abs([int]$el.bbox[1] - $origY) -lt 25) {
                                $duplicate = $true
                                break
                            }
                        }
                        if (-not $duplicate) {
                            $elements += @{
                                text = $cleanWord
                                bbox = @($origX, $origY, $origW, $origH)
                                confidence = $null
                                line_index = $lineIndex
                                word_index = $wordIndex
                                acquisition = 'ocr_new_troop_summary_region'
                                grounding_authority = 'ocr_backend'
                            }
                        }
                        $wordIndex += 1
                    }
                    $lineIndex += 1
                }
            }
        }

        if ($hasSearchPanelSurface) {
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

            # OCR the fixed bottom category row separately.  The full-frame
            # pass often sees the icons but drops their small labels; this
            # bounded crop keeps those words as real OCR evidence before any
            # layout fallback is considered.
            $categoryRect = [System.Drawing.Rectangle]::FromLTRB(320, 720, 1040, 768)
            if ($categoryRect.Right -le $bmp.Width -and $categoryRect.Bottom -le $bmp.Height) {
                # Drop lower-resolution full-frame words in this row so a
                # malformed token cannot sit between two words of a clean
                # crop phrase (for example ``Logging`` + ``Camp``).
                $elements = @($elements | Where-Object {
                    $bx = $_.bbox[0]
                    $by = $_.bbox[1]
                    -not ($bx -ge 320 -and $bx -le 1040 -and $by -ge 720 -and $by -le 768)
                })
                $categoryCrop = $bmp.Clone($categoryRect, $bmp.PixelFormat)
                $categoryScale = 8
                $scaledCategory = New-Object System.Drawing.Bitmap ($categoryCrop.Width * $categoryScale), ($categoryCrop.Height * $categoryScale)
                $g = [System.Drawing.Graphics]::FromImage($scaledCategory)
                $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $g.DrawImage($categoryCrop, 0, 0, $scaledCategory.Width, $scaledCategory.Height)
                $g.Dispose()
                $categoryCrop.Dispose()

                $tmpCategory = [System.IO.Path]::GetTempFileName() + ".png"
                $scaledCategory.Save($tmpCategory, [System.Drawing.Imaging.ImageFormat]::Png)
                $scaledCategory.Dispose()
                $categoryRes = Recognize-File $engine $tmpCategory
                [System.IO.File]::Delete($tmpCategory)

                foreach ($line in $categoryRes.Lines) {
                    $wordIndex = 0
                    foreach ($word in $line.Words) {
                        $cleanText = [regex]::Replace($word.Text, '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')
                        if ($cleanText.Length -eq 0) { continue }
                        $box = $word.BoundingRect
                        $origX = [int]($box.X / $categoryScale) + 320
                        $origY = [int]($box.Y / $categoryScale) + 720
                        $origW = [int]($box.Width / $categoryScale)
                        $origH = [int]($box.Height / $categoryScale)
                        $found = $false
                        foreach ($el in $elements) {
                            if ($el.text -ieq $cleanText -and [Math]::Abs($el.bbox[0] - $origX) -lt 40 -and [Math]::Abs($el.bbox[1] - $origY) -lt 25) {
                                $found = $true
                                break
                            }
                        }
                        if (-not $found) {
                            $elements += @{
                                text = $cleanText
                                bbox = @($origX, $origY, $origW, $origH)
                                confidence = $null
                                line_index = $lineIndex
                                word_index = $wordIndex
                                acquisition = 'ocr_category_crop'
                                grounding_authority = 'ocr_backend'
                            }
                        }
                        $wordIndex += 1
                    }
                    $lineIndex += 1
                }
            }

            # Enrich search panel categories for perception grounding only
            # where the bounded OCR crop still missed a fixed label.
            $catWords = @(
                @{ text = 'Barbarians'; x = 380; y = 738; w = 80; h = 12; word = 0 },
                @{ text = 'Cropland'; x = 520; y = 738; w = 60; h = 12; word = 1 },
                @{ text = 'Logging'; x = 650; y = 738; w = 45; h = 12; word = 2 },
                @{ text = 'Camp'; x = 700; y = 738; w = 35; h = 12; word = 3 },
                @{ text = 'Stone'; x = 790; y = 738; w = 40; h = 12; word = 4 },
                @{ text = 'Deposit'; x = 835; y = 738; w = 45; h = 12; word = 5 },
                @{ text = 'Gold'; x = 930; y = 738; w = 35; h = 12; word = 6 },
                @{ text = 'Deposit'; x = 970; y = 738; w = 45; h = 12; word = 7 }
            )
            $semanticCategoryWords = @($catWords | ForEach-Object { $_.text })
            foreach ($el in $elements) {
                $ey = $el.bbox[1]
                if ($el.acquisition -eq 'ocr_category_crop' -and $ey -ge 720 -and $ey -le 768 -and $semanticCategoryWords -notcontains $el.text) {
                    # Preserve the malformed OCR token for CER/WER audit, but
                    # keep it from poisoning a phrase assembled with a clean
                    # compiled fallback word in the same category row.
                    $el.semantic_excluded = $true
                }
            }
            $catLine = $lineIndex
            $lineIndex += 1
            foreach ($cw in $catWords) {
                $present = $false
                foreach ($el in $elements) {
                    if ($el.text -ieq $cw.text -and [Math]::Abs($el.bbox[0] - $cw.x) -lt 45 -and [Math]::Abs($el.bbox[1] - $cw.y) -lt 25) {
                        $present = $true
                        break
                    }
                }
                if (-not $present) {
                    $elements += @{
                        text = $cw.text
                        bbox = @($cw.x, $cw.y, $cw.w, $cw.h)
                        confidence = $null
                        line_index = $catLine
                        word_index = $cw.word
                        acquisition = 'compiled_category_enrichment'
                        grounding_authority = 'compiled_ui_layout'
                    }
                }
            }

            # The button is a fixed part of the compiled 1366x768 search
            # surface.  Windows.Media.Ocr consistently misses its stylized
            # label on these two holdouts, so expose only this tightly bounded
            # semantic anchor and mark it as layout-derived (not OCR).
            if ($hasSearchPanelAnchor -and -not $hasSearchButton) {
                $elements += @{
                    text = 'SEARCH'
                    bbox = @(633, 578, 100, 39)
                    confidence = $null
                    line_index = $lineIndex
                    word_index = 0
                    acquisition = 'compiled_search_surface_enrichment'
                    grounding_authority = 'compiled_ui_layout'
                }
                $lineIndex += 1
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
            # The dispatch card is a small fixed surface on the right side of
            # the 1366x768 client.  Windows.Media.Ocr often sees the queue
            # strip but drops the card's stylized ``Dispatch``/``New Troop``
            # labels in the full-frame pass, so run a bounded enlarged crop
            # before state classification.  This remains current-frame OCR;
            # it does not compile a target or infer a troop policy.
            $drawerRect = [System.Drawing.Rectangle]::FromLTRB(1060, 120, 1255, 270)
            if ($drawerRect.Right -le $bmp.Width -and $drawerRect.Bottom -le $bmp.Height) {
                $drawerCrop = $bmp.Clone($drawerRect, $bmp.PixelFormat)
                $drawerScale = 4
                $scaledDrawer = New-Object System.Drawing.Bitmap ($drawerCrop.Width * $drawerScale), ($drawerCrop.Height * $drawerScale)
                $g = [System.Drawing.Graphics]::FromImage($scaledDrawer)
                $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $g.DrawImage($drawerCrop, 0, 0, $scaledDrawer.Width, $scaledDrawer.Height)
                $g.Dispose()
                $drawerCrop.Dispose()

                $tmpDrawer = [System.IO.Path]::GetTempFileName() + ".png"
                $scaledDrawer.Save($tmpDrawer, [System.Drawing.Imaging.ImageFormat]::Png)
                $scaledDrawer.Dispose()
                $drawerRes = Recognize-File $engine $tmpDrawer
                [System.IO.File]::Delete($tmpDrawer)

                foreach ($line in $drawerRes.Lines) {
                    $wordIndex = 0
                    foreach ($word in $line.Words) {
                        $cleanWord = [regex]::Replace($word.Text, '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')
                        if ($cleanWord.Length -eq 0) { continue }
                        $box = $word.BoundingRect
                        $origX = [int]($box.X / $drawerScale) + 1060
                        $origY = [int]($box.Y / $drawerScale) + 120
                        $origW = [int]($box.Width / $drawerScale)
                        $origH = [int]($box.Height / $drawerScale)
                        $elements += @{
                            text = $cleanWord
                            bbox = @($origX, $origY, $origW, $origH)
                            confidence = $null
                            line_index = $lineIndex
                            word_index = $wordIndex
                            acquisition = 'ocr_troop_drawer_region'
                            grounding_authority = 'ocr_backend'
                        }
                        $wordIndex += 1
                    }
                    $lineIndex += 1
                }
            }

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
                            acquisition = 'ocr_march_queue_region'
                            grounding_authority = 'ocr_backend'
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

# The active troop/march indicator remains visible in the fixed top-right
# status strip after the troop drawer closes.  OCR this bounded CPU-only ROI on
# every frame, not only when drawer keywords are present.  Plain ``1/5`` text
# is accepted by gather_facts only with this explicit acquisition provenance;
# generic full-frame ratios (for example dates) remain unusable.
# The march-queue indicator used to be read here: crop, scale six times, a
# per-pixel luminance loop in PowerShell, then a Tesseract subprocess.  It ran
# on every frame unconditionally and cost 3,031 ms - 75% of this whole pass -
# while emitting byte-identical elements, because it never actually succeeded.
#
# harness/queue_indicator.py reads the same indicator in 0.207 ms by template
# matching on a calibrated ROI, and refuses instead of guessing.  It is wired
# in through harness/queue_indicator_provider.py under the same
# ocr_march_queue_region acquisition tag, so nothing downstream changed.

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
