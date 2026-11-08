# Windows live verification and evidence upload

Run these commands in PowerShell on the computer running Docker Desktop and the
existing `kind-mlops-assignment` cluster. The native helper uses the trusted tiny
model already included in the repository; Windows Python is not required.

The completed user-operated run is already committed in
`1da4c7e663425c40ee3da78ded2e976357d9705a`. Its
[verification.json](evidence/kubernetes/windows-20261107T192746Z-0a1e3c80/verification.json)
records two ready replicas, successful predictions before and after the selector
fault, traffic failure during the fault, and successful cleanup. The commands
below reproduce that run; another execution or evidence commit is not required
merely to submit the existing repository.

## Update the checkout and run the corrected helper

The first helper version incorrectly passed native command arrays through
`ValueFromRemainingArguments`. Windows PowerShell 5.1 can convert that array to
one string, producing `docker: unknown command: docker info --format {{.OSType}}`.
The corrected wrappers and every call site use explicit named argument arrays.
The regression harness checks actual native argument boundaries; the separate
Windows Actions job runs it under Windows PowerShell 5.1.

```powershell
Set-Location "$env:USERPROFILE\MLOPs-A3-demo"
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Update failed; preserve local changes and report the error.' }

docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not available.' }
kubectl --context kind-mlops-assignment get nodes
if ($LASTEXITCODE -ne 0) { throw 'The kind cluster is not available.' }

powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\windows_deploy.ps1 -ConfirmDeploy -InjectSelectorFailure
if ($LASTEXITCODE -ne 0) { throw 'Verification failed. Report the error; do not label the result successful.' }
```

Docker should report `linux`, and the node should be `Ready`. The script's explicit
flags authorize deployment in namespace `mlops` and the temporary selector fault.
The first image build can take several minutes. The process-scoped execution
policy does not change the saved machine/user policy or override organization
policy.

## Confirm actual deployment, traffic failure and recovery

```powershell
kubectl --context kind-mlops-assignment -n mlops rollout status deployment/inference --timeout=180s
if ($LASTEXITCODE -ne 0) { throw 'The rollout is not ready.' }
kubectl --context kind-mlops-assignment -n mlops get deployments,pods,services,endpoints -o wide

$proof = Get-ChildItem .\evidence\kubernetes -Directory -Filter 'windows-*' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $proof) { throw 'No Windows evidence directory was generated.' }
$result = Get-Content -Raw (Join-Path $proof.FullName 'verification.json') | ConvertFrom-Json
if ($result.status -ne 'VERIFIED_REAL') { throw 'The latest verification did not pass.' }
if ($result.deployment.status.readyReplicas -lt 2) { throw 'Fewer than two replicas were ready.' }
if ($result.baseline_clusterip_probe.reachable -ne $true) { throw 'Baseline Service prediction failed.' }
if (-not $result.selector_failure -or $result.selector_failure.clusterip_probe.reachable -ne $false) { throw 'The injected selector failure was not verified.' }
if ($result.recovery_clusterip_probe.reachable -ne $true) { throw 'Prediction recovery failed.' }
if ($result.cleanup.service_restored -ne $true -or $result.cleanup.errors.Count -ne 0) { throw 'Temporary changes were not cleaned up.' }

[PSCustomObject]@{
    Status = $result.status
    ReadyReplicas = $result.deployment.status.readyReplicas
    PredictionBeforeFault = $result.baseline_clusterip_probe.reachable
    TrafficBlockedByFault = ($result.selector_failure.clusterip_probe.reachable -eq $false)
    PredictionAfterRecovery = $result.recovery_clusterip_probe.reachable
    ModelRunId = $result.model_run_id
    EvidenceDirectory = $proof.FullName
} | Format-List
```

The expected values are `VERIFIED_REAL`, at least `2` ready replicas, and `True`
for the three traffic checks. The probe executes **inside the cluster**, so it
tests actual ClusterIP/DNS routing rather than only reaching a Pod by port-forward.
Events, manifests, endpoints and prediction results are retained in the same
evidence directory. The committed probe result JSONs preserve stdout obtained
through `kubectl logs`. Raw inference-Pod `.log` files are ignored by Git and were
not included in the reviewed upload; the review does not claim to have inspected
those application logs.

## Optional direct local HTTP prediction

Keep this command running in a separate PowerShell window:

```powershell
kubectl --context kind-mlops-assignment -n mlops port-forward service/inference 18001:80
```

In another window:

```powershell
Invoke-RestMethod http://127.0.0.1:18001/health/live
Invoke-RestMethod http://127.0.0.1:18001/health/ready
Invoke-RestMethod http://127.0.0.1:18001/version
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:18001/predict -ContentType 'application/json' -Body '{"instances":[[0,0,0,0,0,0,0,0]]}' | ConvertTo-Json -Depth 10
```

The prediction returns one result and the actual model run ID. Stop the temporary
port-forward with Ctrl+C when finished; the Deployment remains running.

## Cloud route status is a separate check

The cloud agent retried the configured authenticated API request after the first
Windows failure. It again received upstream Envoy/plain-text HTTP 403, before a
Kubernetes response (`evidence/kubernetes/remote_recheck.json`). Fixing local
PowerShell argument binding does not by itself change that cloud route. No token
or cluster health conclusion follows from the proxy denial.

To check the same tunnel from the Windows host without printing a credential:

```powershell
$tunnelUrl = 'https://supplies-rangers-packets-territories.trycloudflare.com'
$readerToken = [string](kubectl --context kind-mlops-assignment -n mlops create token mlops-agent-reader --duration=1h)
if ($LASTEXITCODE -ne 0) { throw 'Cannot obtain the local read-only token.' }
$readerHeaders = @{ Authorization = 'Bearer ' + $readerToken.Trim() }
try {
    $pods = Invoke-RestMethod -Uri ($tunnelUrl + '/api/v1/namespaces/mlops/pods') -Headers $readerHeaders -TimeoutSec 20
    $pods.items | Select-Object @{Name='Name';Expression={$_.metadata.name}}, @{Name='Phase';Expression={$_.status.phase}} | Format-Table
} finally {
    Remove-Variable readerToken,readerHeaders -ErrorAction SilentlyContinue
}
```

Keep the tunnel window open for this optional check. If it was restarted, use the
new public URL; do not share the token or kubeconfig. A successful Windows request
proves that host's authenticated route, not the cloud's route. Complete live
four-system agent verification requires an allowed cloud route or running the
conversational stack locally against the same cluster; see [NEXT_STEPS.md](NEXT_STEPS.md).

## Commit only actual successful Windows evidence

For a new successful rerun, after the verification guards above pass, run from the checkout:

```powershell
$evidencePath = 'evidence/kubernetes/' + $proof.Name
git add -- $evidencePath
git diff --cached --stat
git commit -m "Record real Windows Kubernetes deployment and selector fault recovery"
if ($LASTEXITCODE -ne 0) { throw 'Evidence commit did not complete.' }
git push origin main
if ($LASTEXITCODE -ne 0) { throw 'Push failed; preserve the commit and report the error.' }
git rev-parse HEAD
```

Git may open its normal GitHub sign-in flow on the first push. Do not put a token
in a Git URL or chat. Report the displayed verification summary and commit SHA to
the cloud agent for final review. Do not relabel unrun/blocked agent checks as
passed or change assessment status merely because the deployment script exists.
The repository URL is the submission URL; the instructor determines the grade.
