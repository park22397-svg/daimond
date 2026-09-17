# 옷장 지킴이 — 두 번 눌러 띄웁니다.
#
# VRoid 에서 내보낸 VRM 을 static\wardrobe\_새로넣기 에 넣으면
# 알아서 옷장에 걸립니다. 이 창은 켜 둔 채로 두세요.
#
# ※ 한글이 깨지지 않게 이 파일은 BOM 이 붙은 UTF-8 로 저장돼 있습니다.
#   .bat 로 만들면 한글이 깨집니다.

$ErrorActionPreference = 'Stop'

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

Set-Location -LiteralPath $PSScriptRoot

Write-Host ''
Write-Host '  다이아 옷장 지킴이' -ForegroundColor Cyan
Write-Host '  ------------------'
Write-Host '  VRoid 에서 내보낸 VRM 을 아래 폴더에 넣으세요.'
Write-Host ''
Write-Host "    $PSScriptRoot\static\wardrobe\_새로넣기" -ForegroundColor Yellow
Write-Host ''
Write-Host '  넣으면 바로 옷장에 걸립니다. 브라우저는 새로고침만 하면 됩니다.'
Write-Host '  이 창을 닫으면 멈춥니다.'
Write-Host ''

# 폴더를 열어 준다. 어디에 넣어야 하는지 찾아다니지 않게.
$drop = Join-Path $PSScriptRoot 'static\wardrobe\_새로넣기'
if (-not (Test-Path $drop)) { New-Item -ItemType Directory -Force -Path $drop | Out-Null }
Start-Process explorer.exe $drop

python _watch_wardrobe.py
