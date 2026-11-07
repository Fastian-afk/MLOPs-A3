<#
.SYNOPSIS
Build/load the trusted tiny inference fixture into the existing local kind cluster.
.DESCRIPTION
Run from a reviewed local checkout, in PowerShell with Docker Desktop Linux
containers, Git, kind and kubectl available. Python is not required on Windows.
Writes are limited to namespace mlops and require -ConfirmDeploy. The optional
Service selector fault additionally requires -InjectSelectorFailure. Credentials
are neither exported nor printed. No execution-policy or TLS settings are changed.
#>
[CmdletBinding()]
param(
    [switch]$ConfirmDeploy,
    [switch]$InjectSelectorFailure,
    [ValidatePattern('^[a-z0-9][a-z0-9-]{0,40}$')]
    [string]$ClusterName = 'mlops-assignment',
    [string]$BuildCaBundle
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmDeploy) {
    throw 'Review this script, then pass -ConfirmDeploy to authorize deployment in namespace mlops.'
}
$repoRoot = Split-Path -Parent $PSScriptRoot
$context = 'kind-' + $ClusterName
$namespace = 'mlops'
$kubectl = (Get-Command kubectl -ErrorAction Stop).Source
foreach ($tool in @('docker', 'kind', 'git')) { Get-Command $tool -ErrorAction Stop | Out-Null }

function Invoke-Checked {
    param([string]$Executable, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $result = & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable failed with exit code $LASTEXITCODE" }
    return $result
}
function Kube {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    Invoke-Checked $kubectl (@('--context', $context, '--namespace', $namespace) + $Arguments)
}
function Write-Json {
    param([string]$Path, [object]$Value)
    $json = $Value | ConvertTo-Json -Depth 80
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
}
function Read-Resource {
    param([string]$Kind, [string]$Name)
    return ((Kube @('get', $Kind, $Name, '-o', 'json')) -join "`n" | ConvertFrom-Json)
}

Push-Location $repoRoot
$probeNames = New-Object 'System.Collections.Generic.List[string]'
$serviceChanged = $false
$timestamp = [DateTime]::UtcNow.ToString('o')
$evidenceDir = Join-Path $repoRoot ('evidence\kubernetes\windows-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
$record = [ordered]@{ timestamp = $timestamp; status = 'FAILED'; scope = 'real operator-run local kind cluster'; context = $context; namespace = $namespace }

function Run-ClusterProbe {
    param([bool]$ExpectFailure)
    $name = 'mlops-probe-' + [Guid]::NewGuid().ToString('N').Substring(0, 10)
    $probeNames.Add($name)
    # The client executes inside the cluster, so it exercises ClusterIP/DNS routing
    # rather than port-forwarding directly to a selected Pod.
    $code = @'
import json,urllib.request,urllib.error
base='http://inference.mlops.svc.cluster.local'
result={}
try:
    for path in ['/health/live','/health/ready','/version']:
        with urllib.request.urlopen(base+path,timeout=5) as response:
            result[path]={'http_status':response.status,'body':json.load(response)}
    request=urllib.request.Request(base+'/predict',data=b'{"instances":[[0,0,0,0,0,0,0,0]]}',headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=5) as response:
        result['/predict']={'http_status':response.status,'body':json.load(response)}
    result['reachable']=True
except (urllib.error.URLError,TimeoutError,OSError) as error:
    result['reachable']=False
    result['error_type']=type(error).__name__
print(json.dumps(result))
'@
    $pod = @{
        apiVersion = 'v1'; kind = 'Pod'
        metadata = @{ name = $name; namespace = $namespace; labels = @{ app = 'mlops-route-probe' } }
        spec = @{
            restartPolicy = 'Never'; automountServiceAccountToken = $false
            securityContext = @{ runAsNonRoot = $true; runAsUser = 10001; runAsGroup = 10001 }
            containers = @(@{
                name = 'probe'; image = $image; imagePullPolicy = 'IfNotPresent'
                command = @('python', '-c', $code)
                resources = @{ requests = @{ cpu = '25m'; memory = '64Mi' }; limits = @{ cpu = '200m'; memory = '128Mi' } }
                securityContext = @{ allowPrivilegeEscalation = $false; readOnlyRootFilesystem = $true; capabilities = @{ drop = @('ALL') } }
            })
        }
    }
    $file = Join-Path $evidenceDir ($name + '.json')
    Write-Json $file $pod
    Kube @('apply', '-f', $file) | Out-Host
    Kube @('wait', '--for=jsonpath={.status.phase}=Succeeded', ('pod/' + $name), '--timeout=90s') | Out-Host
    $text = (Kube @('logs', $name)) -join "`n"
    $result = $text | ConvertFrom-Json
    Write-Json (Join-Path $evidenceDir ($name + '-result.json')) $result
    if ($ExpectFailure -and $result.reachable) { throw 'Injected selector fault unexpectedly remained reachable.' }
    if (-not $ExpectFailure -and -not $result.reachable) { throw 'Prediction Service is not reachable from inside the cluster.' }
    if (-not $ExpectFailure) {
        if ($result.'/version'.body.run_id -ne $manifest.run_id) { throw 'Served model lineage differs from the trusted fixture.' }
        if ($result.'/predict'.body.predictions.Count -ne 1) { throw 'Prediction response did not contain one result.' }
    }
    return $result
}

try {
    $osType = [string](Invoke-Checked docker @('info', '--format', '{{.OSType}}'))
    if ($osType.Trim() -ne 'linux') { throw 'Docker Desktop must use Linux containers.' }
    $clusters = @(Invoke-Checked kind @('get', 'clusters'))
    if ($clusters -notcontains $ClusterName) { throw "Create the local kind cluster '$ClusterName' first." }
    $revision = ([string](Invoke-Checked git @('rev-parse', '--verify', 'HEAD'))).Trim()
    if ($revision -notmatch '^[0-9a-f]{40}$') { throw 'Cannot derive an immutable image tag from the local Git commit.' }
    $sourceChanges = @(Invoke-Checked git @('status', '--porcelain', '--', 'inference', 'Dockerfile.inference', 'demo_artifacts', 'kubernetes', 'scripts/windows_deploy.ps1'))
    if ($sourceChanges.Count -gt 0) { throw 'Commit or preserve/review modified deployment source before building an immutable Git-tagged image.' }
    $image = 'mlops-inference:git-' + $revision
    $manifest = Get-Content -Raw (Join-Path $repoRoot 'demo_artifacts\metadata.json') | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.run_id -notmatch '^[0-9a-f]{32}$' -or -not $manifest.quality_gate.passed) {
        throw 'Trusted fixture metadata is invalid or does not record a passing quality gate.'
    }
    $fixture = Join-Path $repoRoot 'demo_artifacts\model.joblib'
    $actualHash = (Get-FileHash -Algorithm SHA256 $fixture).Hash.ToLowerInvariant()
    if ($actualHash -ne $manifest.sha256) { throw 'Trusted demo artifact checksum mismatch.' }
    $artifactDir = Join-Path $repoRoot 'artifacts'
    New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
    $destination = Join-Path $artifactDir 'model.joblib'
    if (Test-Path $destination) {
        if ((Get-FileHash -Algorithm SHA256 $destination).Hash.ToLowerInvariant() -ne $actualHash) {
            throw 'Existing artifacts/model.joblib differs; preserve it or move it before selecting this demo fixture.'
        }
    } else { Copy-Item -LiteralPath $fixture -Destination $destination }
    $buildArguments = @('build', '-f', 'Dockerfile.inference', '-t', $image)
    if ($BuildCaBundle) {
        $ca = (Resolve-Path -LiteralPath $BuildCaBundle).Path
        $buildArguments += @('--secret', ('id=proxy_ca,src=' + $ca))
    }
    Invoke-Checked docker ($buildArguments + @('.')) | Out-Host
    Invoke-Checked kind @('load', 'docker-image', '--name', $ClusterName, $image) | Out-Host
    foreach ($file in @('namespace.yaml', 'configmap.yaml', 'service.yaml', 'rbac.yaml')) {
        Kube @('apply', '-f', (Join-Path $repoRoot ('kubernetes\' + $file))) | Out-Host
    }
    $deployment = Invoke-Checked $kubectl @('set', 'image', '--local', '-f', 'kubernetes/deployment.yaml', ('inference=' + $image), '-o', 'json')
    $deploymentObject = ($deployment -join "`n") | ConvertFrom-Json
    $deploymentObject.metadata | Add-Member -Force -NotePropertyName annotations -NotePropertyValue @{
        'mlops.model-run-id' = [string]$manifest.run_id
        'mlops.git-commit' = $revision
        'mlops.model-git-commit' = [string]$manifest.training_git_commit
    }
    $deploymentFile = Join-Path $evidenceDir 'deployment-request.json'
    Write-Json $deploymentFile $deploymentObject
    Kube @('apply', '-f', $deploymentFile) | Out-Host
    Kube @('rollout', 'status', 'deployment/inference', '--timeout=180s') | Out-Host
    $state = Read-Resource 'deployment' 'inference'
    if ($state.spec.replicas -lt 2 -or $state.status.readyReplicas -lt 2 -or $state.status.availableReplicas -lt 2) {
        throw 'Deployment must have at least two desired, Ready and available replicas.'
    }
    $record.image = $image
    $record.model_run_id = $manifest.run_id
    $record.model_sha256 = $actualHash
    $record.model_training_git_commit = $manifest.training_git_commit
    $record.deployment = $state
    $record.service = Read-Resource 'service' 'inference'
    $record.endpoints = Read-Resource 'endpoints' 'inference'
    $record.baseline_clusterip_probe = Run-ClusterProbe $false

    if ($InjectSelectorFailure) {
        $patchFile = Join-Path $evidenceDir 'selector-fault-patch.json'
        Write-Json $patchFile @{ spec = @{ selector = @{ app = 'mlops-deliberately-no-match' } } }
        $serviceChanged = $true
        Kube @('patch', 'service', 'inference', '--type=merge', '--patch-file', $patchFile) | Out-Host
        Start-Sleep -Seconds 5
        $record.selector_failure = @{
            service = (Read-Resource 'service' 'inference')
            endpoints = (Read-Resource 'endpoints' 'inference')
            clusterip_probe = (Run-ClusterProbe $true)
            diagnosis = 'Operator changed the Service selector; the inference Pods remain healthy but no matching ready endpoints route Service traffic.'
        }
        Kube @('apply', '-f', 'kubernetes/service.yaml') | Out-Host
        $serviceChanged = $false
        Start-Sleep -Seconds 5
        $record.recovery_clusterip_probe = Run-ClusterProbe $false
    }
    $record.pods = ((Kube @('get', 'pods', '-l', 'app=inference', '-o', 'json')) -join "`n" | ConvertFrom-Json)
    $record.events = @()
    foreach ($pod in $record.pods.items) {
        $events = ((Kube @('get', 'events', '--field-selector', ('involvedObject.name=' + $pod.metadata.name), '-o', 'json')) -join "`n" | ConvertFrom-Json)
        $record.events += $events.items
        $log = (Kube @('logs', $pod.metadata.name, '--tail=100')) -join "`n"
        [IO.File]::WriteAllText((Join-Path $evidenceDir ($pod.metadata.name + '.log')), $log, (New-Object Text.UTF8Encoding($false)))
    }
    $record.status = 'VERIFIED_REAL'
    Write-Host 'Two-replica rollout and real in-cluster Service prediction verified.'
    Write-Host ('Evidence directory: ' + $evidenceDir)
} catch {
    $record.error = $_.Exception.GetType().Name + ': ' + $_.Exception.Message
    throw
} finally {
    $cleanupErrors = New-Object 'System.Collections.Generic.List[string]'
    if ($serviceChanged) {
        try {
            Kube @('apply', '-f', 'kubernetes/service.yaml') | Out-Host
            $serviceChanged = $false
        } catch { $cleanupErrors.Add('Service restoration failed; apply kubernetes/service.yaml in the approved context.') }
    }
    foreach ($name in $probeNames) {
        try { Kube @('delete', 'pod', $name, '--ignore-not-found=true', '--wait=false') | Out-Host }
        catch { $cleanupErrors.Add('Probe Pod cleanup failed: ' + $name) }
    }
    $record.cleanup = @{ service_restored = (-not $serviceChanged); errors = @($cleanupErrors.ToArray()) }
    if ($cleanupErrors.Count -gt 0) { $record.status = 'FAILED' }
    try { Write-Json (Join-Path $evidenceDir 'verification.json') $record }
    finally { Pop-Location }
    if ($cleanupErrors.Count -gt 0) {
        throw ('Cleanup needs operator attention: ' + ($cleanupErrors -join '; '))
    }
}
