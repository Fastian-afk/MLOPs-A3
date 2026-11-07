# Connect a Windows Docker Desktop cluster to the cloud agent

This procedure creates a local kind cluster and a temporary public HTTPS tunnel
to its authenticated Kubernetes API. It does not disable TLS verification or
Kubernetes authentication. The cloud agent receives only a namespaced read-only
ServiceAccount token, never an administrator kubeconfig. Keep the PC awake and
Docker Desktop and the tunnel running during verification. No router forwarding
or inbound Windows firewall opening is required.

This is a connection prerequisite. A connected empty cluster is not an inference
deployment: image distribution, two ready replicas, predictions and the real
cluster fault/recovery checks still need to run afterward.

## 1. Install tools in Administrator PowerShell

Docker Desktop must be running with Linux containers selected. Run:

```powershell
$ErrorActionPreference = 'Stop'
winget install --exact --id Kubernetes.kind --source winget --accept-package-agreements --accept-source-agreements
winget install --exact --id Kubernetes.kubectl --source winget --accept-package-agreements --accept-source-agreements
winget install --exact --id Cloudflare.cloudflared --source winget --accept-package-agreements --accept-source-agreements
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
docker info --format '{{.OSType}}'
```

The final line must print `linux`. Already-installed package messages are normal.
If commands are still unavailable, reopen Administrator PowerShell. Stop if Docker
cannot connect, a package install fails, or the output is `windows`.

## 2. Create the cluster and its read-only account

```powershell
$ErrorActionPreference = 'Stop'
$clusterContext = 'kind-mlops-assignment'
$clusters = @(kind get clusters)
if ($LASTEXITCODE -ne 0) { throw 'Cannot list kind clusters' }
if ($clusters -notcontains 'mlops-assignment') {
    kind create cluster --name mlops-assignment --wait 180s
    if ($LASTEXITCODE -ne 0) { throw 'Cluster creation failed' }
}
kubectl --context $clusterContext wait --for=condition=Ready nodes --all --timeout=180s
if ($LASTEXITCODE -ne 0) { throw 'Cluster nodes are not Ready' }
kubectl --context $clusterContext apply -f https://raw.githubusercontent.com/Fastian-afk/MLOPs-A3/main/kubernetes/namespace.yaml
if ($LASTEXITCODE -ne 0) { throw 'Namespace setup failed' }
kubectl --context $clusterContext apply -f https://raw.githubusercontent.com/Fastian-afk/MLOPs-A3/main/kubernetes/rbac.yaml
if ($LASTEXITCODE -ne 0) { throw 'Read-only account setup failed' }
kubectl --context $clusterContext get nodes
```

Use the explicit context to avoid operating on another existing cluster. The role
grants get/list access to Pods, logs, events, Services, endpoints and Deployments
only in namespace `mlops`.

## 3. Start a TLS-verified temporary tunnel

Run in the same PowerShell window and leave it open:

```powershell
$clusterContext = 'kind-mlops-assignment'
$apiUrl = [string](kubectl --context $clusterContext config view --minify -o 'jsonpath={.clusters[0].cluster.server}')
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($apiUrl)) { throw 'Cannot read API address' }
$caData = [string](kubectl --context $clusterContext config view --minify --flatten --raw -o 'jsonpath={.clusters[0].cluster.certificate-authority-data}')
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($caData)) { throw 'Cannot read public API CA' }
$apiUrl = $apiUrl.Trim()
$caPath = Join-Path $env:TEMP 'mlops-kind-public-ca.crt'
[IO.File]::WriteAllBytes($caPath, [Convert]::FromBase64String($caData.Trim()))
cloudflared tunnel --protocol http2 --url $apiUrl --origin-ca-pool $caPath
```

Only the public CA certificate is exported; the JSONPath does not output admin
credentials. The original API hostname/IP remains unchanged so its certificate
can be verified. Do not add `--no-tls-verify` if the tunnel fails; inspect the error.

Cloudflared prints an address like `https://some-words.trycloudflare.com`.
Send only that public URL to the cloud agent. The exact hostname must be added to
the cloud network policy and token destination before remote access can work.
The URL changes if the tunnel is restarted. Cloudflare Quick Tunnels may be
unavailable when an existing cloudflared configuration is present; do not delete
an existing configuration to work around that—report the error instead.

## 4. Supply a short-lived read-only token securely

After the cloud agent has prepared the `MLOPS_KUBE_API_TOKEN` secret field for the
actual tunnel hostname, open a second PowerShell window and run:

```powershell
kubectl --context kind-mlops-assignment -n mlops create token mlops-agent-reader --duration=1h | Set-Clipboard
if ($LASTEXITCODE -ne 0) { throw 'Token creation failed' }
```

Paste the clipboard into that secure secret field in environment settings, save
and apply/publish the configuration, then clear the clipboard with `Set-Clipboard
-Value ''`. Do not paste the token, administrator kubeconfig or private key into
chat or Git. This token cannot create, edit or delete cluster resources. If it
expires, regenerate it and replace the secure value.

The cloud-side non-secret setting is `MLOPS_KUBE_API_URL` set to the actual tunnel
URL. Its client uses the inherited cloud HTTPS proxy and verified public TLS;
the kind origin CA belongs only to the local cloudflared connection.

## 5. Verification and cleanup

The cloud agent first verifies authenticated namespaced reads, then coordinates
image loading and operator-authorized deployment. Deployment/fault changes are
separate explicit operator actions; the read-only token does not grant them.
Record the real two-replica rollout, endpoints, logs/events, prediction/version,
agent conversations, selector failure and corrected recovery. Preserve current
`BLOCKED` evidence until these checks actually succeed.

When finished, press Ctrl+C in the tunnel window. To revoke this dedicated account's
access, the operator can delete its RoleBinding; delete the entire kind cluster
only when its workloads are no longer needed. No local or remote cluster was
created by documenting this procedure.
