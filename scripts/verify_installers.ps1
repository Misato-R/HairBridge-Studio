param(
    [Parameter(Mandatory=$true)][string]$Blender,
    [Parameter(Mandatory=$true)][string]$ShpZip
)
$ErrorActionPreference='Stop'
$repositoryRoot=Split-Path -Parent $PSScriptRoot
$blenderExecutable=(Resolve-Path -LiteralPath $Blender).Path
$shpInstaller=(Resolve-Path -LiteralPath $ShpZip).Path
$verificationRoot=Join-Path $repositoryRoot ('data\verification\'+[guid]::NewGuid().ToString())
$verificationProfile=Join-Path $verificationRoot 'profile'
New-Item -ItemType Directory -Path $verificationProfile -Force | Out-Null
$priorResources=$env:BLENDER_USER_RESOURCES
try {
    $env:BLENDER_USER_RESOURCES=$verificationProfile
    & $blenderExecutable --background --factory-startup --python-exit-code 1 --python (Join-Path $PSScriptRoot 'verify_installers.py') -- --profile $verificationProfile --shp-zip $shpInstaller --report (Join-Path $verificationRoot 'report.json')
    if($LASTEXITCODE -ne 0){throw "Blender verification failed ($LASTEXITCODE)."}
    Write-Output "Verification record: $(Join-Path $verificationRoot 'report.json')"
} finally {
    $env:BLENDER_USER_RESOURCES=$priorResources
}
