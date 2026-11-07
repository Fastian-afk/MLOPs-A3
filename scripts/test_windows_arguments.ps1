<#
.SYNOPSIS
Check the production helper's actual native argument boundaries without Docker or Kubernetes.
.DESCRIPTION
On Windows this compiles a tiny native console recorder and exercises the real
Invoke-Checked/Kube definitions extracted from windows_deploy.ps1. No deployment
code is sourced or run. Desktop PowerShell 5.1 also reproduces the old remaining-
arguments bug to prove this regression catches the reported Windows failure.
#>
[CmdletBinding()]
param(
    [string]$OutputPath,
    [switch]$RequireWindowsPowerShell51
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$onWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
if ($RequireWindowsPowerShell51 -and (-not $onWindows -or $PSVersionTable.PSVersion.Major -ne 5)) {
    throw 'This job must exercise actual Windows PowerShell 5.1.'
}
if (Test-Path Variable:PSNativeCommandArgumentPassing) { $PSNativeCommandArgumentPassing = 'Legacy' }
$helperPath = Join-Path $PSScriptRoot 'windows_deploy.ps1'
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($helperPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw 'The deployment helper has a PowerShell syntax error.' }
$definitions = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -in @('Invoke-Checked', 'Kube')
}, $true))
if ($definitions.Count -ne 2) { throw 'Expected both production native-command wrappers.' }
. ([scriptblock]::Create(($definitions | ForEach-Object { $_.Extent.Text }) -join "`n"))

$testDir = Join-Path ([IO.Path]::GetTempPath()) ('mlops argv with spaces ' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testDir | Out-Null
$checks = New-Object 'System.Collections.Generic.List[string]'
$legacyBugReproduced = $null
try {
    if ($onWindows) {
        $recorder = Join-Path $testDir 'native recorder.exe'
        $source = @'
using System;
using System.Text;
public class NativeArgumentRecorder {
    public static int Main(string[] args) {
        if (args.Length > 0 && args[0] == "__exit_7__") return 7;
        if (args.Length > 0 && args[0] == "__stderr__") Console.Error.WriteLine("native diagnostic");
        Console.WriteLine(args.Length);
        foreach (string value in args) Console.WriteLine(Convert.ToBase64String(Encoding.UTF8.GetBytes(value)));
        return 0;
    }
}
'@
        Add-Type -TypeDefinition $source -OutputAssembly $recorder -OutputType ConsoleApplication
    } else {
        # Portable coverage supplements, but never substitutes for, the Windows
        # Desktop 5.1 job. This is an actual executable process, not a PS mock.
        $recorder = Join-Path $testDir 'native recorder'
        $python = (Get-Command python3 -ErrorAction Stop).Source
        $source = @'
import base64,sys
args=sys.argv[1:]
if args and args[0]=='__exit_7__': raise SystemExit(7)
if args and args[0]=='__stderr__': print('native diagnostic',file=sys.stderr)
print(len(args))
for arg in args: print(base64.b64encode(arg.encode()).decode())
'@
        [IO.File]::WriteAllText($recorder, '#!' + $python + "`n" + $source, (New-Object Text.UTF8Encoding($false)))
        & chmod +x $recorder
        if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare portable native argument recorder.' }
    }

    function Decode-Arguments {
        param([object[]]$Lines)
        $nativeLines = @($Lines)
        $count = [int]$nativeLines[0]
        if ($nativeLines.Count -ne ($count + 1)) { throw 'Native recorder output was mixed with diagnostic text.' }
        for ($index = 1; $index -le $count; $index++) {
            [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$nativeLines[$index]))
        }
    }
    function Assert-Arguments {
        param([string]$Name, [string[]]$Actual, [string[]]$Expected)
        if ($Actual.Count -ne $Expected.Count) { throw "$Name argument count differs: $($Actual.Count) vs $($Expected.Count)" }
        for ($index = 0; $index -lt $Expected.Count; $index++) {
            if ($Actual[$index] -cne $Expected[$index]) { throw "$Name argument $index differs." }
        }
        $checks.Add($Name)
    }

    $expected = @('info', '--format', '{{.OSType}}')
    $dockerCalls = @($ast.FindAll({ param($node)
        $node -is [Management.Automation.Language.CommandAst] -and
            $node.GetCommandName() -eq 'Invoke-Checked' -and $node.Extent.Text -match 'OSType'
    }, $true))
    if ($dockerCalls.Count -ne 1) { throw 'Expected the actual production Docker info command.' }
    Set-Alias -Name docker -Value $recorder
    $actual = @(Decode-Arguments -Lines @(& ([scriptblock]::Create($dockerCalls[0].Extent.Text))))
    Assert-Arguments -Name 'docker_info_three_native_arguments' -Actual $actual -Expected $expected

    $expected = @('apply', '-f', (Join-Path $testDir 'directory with spaces\pod.json'), '--for=jsonpath={.status.phase}=Succeeded')
    $actual = @(Decode-Arguments -Lines @(Invoke-Checked -Executable $recorder -ArgumentList $expected))
    Assert-Arguments -Name 'paths_spaces_and_jsonpath_preserved' -Actual $actual -Expected $expected

    $context = 'kind-mlops-assignment'
    $namespace = 'mlops'
    $kubectl = $recorder
    $actual = @(Decode-Arguments -Lines @(Kube -ArgumentList @('logs', 'inference-one', '--tail=100')))
    $expected = @('--context', $context, '--namespace', $namespace, 'logs', 'inference-one', '--tail=100')
    Assert-Arguments -Name 'kubectl_context_namespace_and_arguments_separate' -Actual $actual -Expected $expected

    $rejected = $false
    try { Invoke-Checked -Executable $recorder -ArgumentList @('__exit_7__') | Out-Null }
    catch { $rejected = $_.Exception.Message -match 'exit code 7' }
    if (-not $rejected) { throw 'A failing native process was not rejected.' }
    $checks.Add('native_nonzero_exit_rejected')

    $actual = @(Decode-Arguments -Lines @(Invoke-Checked -Executable $recorder -ArgumentList @('__stderr__')))
    Assert-Arguments -Name 'successful_stderr_does_not_corrupt_stdout' -Actual $actual -Expected @('__stderr__')

    if ($onWindows -and $PSVersionTable.PSVersion.Major -eq 5) {
        function Invoke-OldRemainingBinding {
            param([string]$Executable, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
            & $Executable @Arguments
        }
        $old = @(Decode-Arguments -Lines @(Invoke-OldRemainingBinding $recorder @('info', '--format', '{{.OSType}}')))
        $legacyBugReproduced = $old.Count -ne 3 -or $old[0] -ne 'info'
        if (-not $legacyBugReproduced) { throw 'The Desktop 5.1 baseline did not reproduce the reported remaining-arguments bug.' }
        $checks.Add('original_windows51_remaining_arguments_bug_reproduced')
    }

    $report = [ordered]@{
        timestamp = [DateTime]::UtcNow.ToString('o')
        status = 'VERIFIED_REAL'
        scope = 'Actual native process argument boundaries; no Docker/Kubernetes service commands executed'
        operating_system = [Environment]::OSVersion.Platform.ToString()
        powershell_version = $PSVersionTable.PSVersion.ToString()
        windows_powershell51 = ($onWindows -and $PSVersionTable.PSVersion.Major -eq 5)
        native_argument_mode = 'Legacy on PowerShell 7; intrinsic Desktop behavior on Windows PowerShell 5.1'
        original_bug_reproduced = $legacyBugReproduced
        checks = @($checks.ToArray())
    }
    if ($OutputPath) {
        $fullOutput = [IO.Path]::GetFullPath($OutputPath)
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $fullOutput) | Out-Null
        [IO.File]::WriteAllText($fullOutput, ($report | ConvertTo-Json -Depth 10) + "`n", (New-Object Text.UTF8Encoding($false)))
    }
    $report | ConvertTo-Json -Depth 10
} finally {
    Remove-Item -LiteralPath $testDir -Recurse -Force
}
