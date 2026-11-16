$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$request = $env:RESC_USB_REQUEST | ConvertFrom-Json
if ($request.drive -notmatch '^[A-Z]$' -or
    $request.operation -notin @('format', 'write-canary') -or
    $request.filesystem -notin @('exfat', 'fat32')) { throw 'Invalid request' }

function Get-CheckedTarget {
    param([string]$Letter)
    if ($Letter -eq 'C') { throw 'C: is protected' }
    $partitions = @(Get-Partition -DriveLetter $Letter -ErrorAction Stop)
    if ($partitions.Count -ne 1) { throw 'Ambiguous drive mapping' }
    $disk = $partitions[0] | Get-Disk -ErrorAction Stop
    if ($disk.Number -eq 0) { throw 'Disk 0 is protected' }
    if ($disk.BusType -ne 'USB') { throw 'Only USB disks are permitted' }
    if ($disk.IsBoot -or $disk.IsSystem -or $disk.IsOffline -or $disk.IsReadOnly) {
        throw 'Boot/system/offline/read-only disk is protected'
    }
    $allParts = @(Get-Partition -DiskNumber $disk.Number -ErrorAction Stop)
    if (@($allParts | Where-Object { $_.IsBoot -or $_.IsSystem -or $_.DriveLetter -eq 'C' }).Count) {
        throw 'Disk contains a protected partition'
    }
    $systemLetter = $env:SystemDrive.TrimEnd(':')
    foreach ($protected in @('C', $systemLetter)) {
        $systemDisk = Get-Partition -DriveLetter $protected -ErrorAction Stop | Get-Disk -ErrorAction Stop
        if ($systemDisk.Number -eq $disk.Number) { throw 'OS disk is protected' }
    }
    $pagefiles = @(Get-CimInstance Win32_PageFileUsage -ErrorAction Stop)
    $configured = @(Get-CimInstance Win32_PageFileSetting -ErrorAction Stop)
    foreach ($pagefile in @($pagefiles) + @($configured)) {
        if ($pagefile.Name -notmatch '^([A-Za-z]):\\') { throw 'Unknown pagefile location' }
        $pageDisk = Get-Partition -DriveLetter $Matches[1] -ErrorAction Stop | Get-Disk -ErrorAction Stop
        if ($pageDisk.Number -eq $disk.Number) { throw 'Pagefile disk is protected' }
    }
    if (-not $disk.UniqueId -or -not $disk.SerialNumber.Trim() -or $disk.Size -le 0) {
        throw 'Incomplete device identity'
    }
    if (@(Get-Disk | Where-Object UniqueId -eq $disk.UniqueId).Count -ne 1) {
        throw 'Non-unique device identity'
    }
    $volume = $partitions[0] | Get-Volume -ErrorAction Stop
    if (-not $volume.Path -or $volume.Path -notmatch '^\\\\\?\\Volume\{[0-9A-Fa-f-]+\}\\$') {
        throw 'Missing volume GUID path'
    }
    return [pscustomobject]@{
        number = [int]$disk.Number
        unique_id = [string]$disk.UniqueId
        serial = $disk.SerialNumber.Trim()
        size = [long]$disk.Size
        sector_size = [int]$disk.LogicalSectorSize
        volume = $volume.Path
        drive = $Letter
    }
}

$identity = Get-CheckedTarget $request.drive
if ($request.operation -eq 'format') {
    if ($identity.size -gt 2TB) { throw 'MBR formatting is limited to disks up to 2 TiB' }
    if ($request.filesystem -eq 'fat32' -and $identity.size -gt 32GB) {
        throw 'Native FAT32 formatting is restricted to disks up to 32 GiB; select exFAT'
    }
}
if (-not $request.execute) {
    $identity | ConvertTo-Json -Compress
    exit 0
}
foreach ($field in @('number','unique_id','serial','size','sector_size','volume','drive')) {
    if ($identity.$field -cne $request.expected.$field) { throw "Device changed: $field" }
}
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Execution requires an elevated administrator process'
}

# Preserve an external audit record before any write to the USB.
$auditRoot = Join-Path $env:LOCALAPPDATA 'resc\usb-lab'
$auditLetter = [IO.Path]::GetPathRoot($auditRoot).TrimEnd('\').TrimEnd(':')
if ($auditLetter -notmatch '^[A-Za-z]$') { throw 'Audit location must be on a local drive' }
if ((Get-Partition -DriveLetter $auditLetter | Get-Disk).Number -eq $identity.number) {
    throw 'Audit must be stored on another disk'
}
$ancestor = [IO.DirectoryInfo]::new($auditRoot)
while ($null -ne $ancestor) {
    if ($ancestor.Exists -and ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Linked audit directory is forbidden'
    }
    $ancestor = $ancestor.Parent
}
$runId = [Guid]::NewGuid().ToString('N')
[void][IO.Directory]::CreateDirectory($auditRoot)
$auditFile = Join-Path $auditRoot ($runId + '.json')
$report = [ordered]@{ status = 'STARTED'; operation = $request.operation; device = $identity; files = @() }
$auditStream = [IO.FileStream]::new($auditFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
    $auditBytes = [Text.Encoding]::UTF8.GetBytes(($report | ConvertTo-Json -Depth 8))
    $auditStream.Write($auditBytes, 0, $auditBytes.Length)
    $auditStream.Flush($true)
} finally { $auditStream.Dispose() }
try {
    # Recheck the mapping immediately before the destructive command.
    $current = Get-CheckedTarget $request.drive
    if (($current | ConvertTo-Json -Compress) -cne ($identity | ConvertTo-Json -Compress)) {
        throw 'Device changed before execution'
    }
    if ($request.operation -eq 'format') {
        $disk = Get-Disk -UniqueId $identity.unique_id -ErrorAction Stop
        $disk | Clear-Disk -RemoveData -RemoveOEM -Confirm:$false -ErrorAction Stop
        $disk = Get-Disk -UniqueId $identity.unique_id -ErrorAction Stop
        if ($disk.PartitionStyle -eq 'RAW') {
            $disk | Initialize-Disk -PartitionStyle MBR -ErrorAction Stop | Out-Null
        } elseif ($disk.PartitionStyle -ne 'MBR') {
            throw 'Disk was not cleared to RAW/MBR'
        }
        $disk = Get-Disk -UniqueId $identity.unique_id -ErrorAction Stop
        $partition = $disk | New-Partition -UseMaximumSize -Offset 1MB -DriveLetter $request.drive -ErrorAction Stop
        $partition | Format-Volume -FileSystem $request.filesystem -NewFileSystemLabel 'RESC_USB' -Confirm:$false -Force -ErrorAction Stop | Out-Null
        $after = Get-CheckedTarget $request.drive
        foreach ($field in @('number','unique_id','serial','size','sector_size')) {
            if ($after.$field -cne $identity.$field) { throw 'Device identity changed after format' }
        }
        if ((Get-Disk -UniqueId $identity.unique_id).PartitionStyle -ne 'MBR') { throw 'MBR readback failed' }
        if ((Get-Volume -DriveLetter $request.drive).FileSystem -ine $request.filesystem) { throw 'Filesystem readback failed' }
        $identity = $after
    }
    Add-Type -TypeDefinition @'
using System.Security.Cryptography;
public static class RescCanary {
    public static byte[] Create(int length) {
        byte[] data = new byte[length];
        using (var rng = RandomNumberGenerator.Create()) { rng.GetBytes(data); }
        for (int i = 0; i < data.Length; i++) data[i] = (byte)(1 + data[i] % 254);
        return data;
    }
}
'@
    $folder = $identity.volume + 'resc-canary-' + $runId
    if ([IO.Directory]::Exists($folder)) { throw 'Canary directory already exists' }
    [void][IO.Directory]::CreateDirectory($folder)
    for ($index = 0; $index -lt 4; $index++) {
        $payload = [RescCanary]::Create(1MB)
        $filename = $runId + '-' + $index + '.bin'
        $path = Join-Path $folder $filename
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $expected = [BitConverter]::ToString($sha.ComputeHash($payload)).Replace('-', '').ToLowerInvariant() }
        finally { $sha.Dispose() }
        $entry = [ordered]@{ name = $filename; bytes = $payload.Length; sha256 = $expected; verified_t1 = $false }
        $report.files += $entry
        [IO.File]::WriteAllText($auditFile, ($report | ConvertTo-Json -Depth 8))
        $stream = [IO.FileStream]::new($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None, 65536, [IO.FileOptions]::WriteThrough)
        try { $stream.Write($payload, 0, $payload.Length); $stream.Flush($true) }
        finally { $stream.Dispose() }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected) {
            throw "Canary readback failed: $filename"
        }
        $entry.verified_t1 = $true
    }
    $report.status = 'T1_VERIFIED_T2_PENDING'
    $report.canary_directory = $folder
    $report.audit_manifest = $auditFile
    $report.limitation = 'Four logical files, not physical LBA coverage or full-capacity verification. Reconnect testing is pending.'
    [IO.File]::WriteAllText((Join-Path $folder 'manifest.json'), ($report | ConvertTo-Json -Depth 8))
} catch {
    $report.status = 'FAILED_PARTIAL'
    $report.error = $_.Exception.Message
    [IO.File]::WriteAllText($auditFile, ($report | ConvertTo-Json -Depth 8))
    throw
}
[IO.File]::WriteAllText($auditFile, ($report | ConvertTo-Json -Depth 8))
$report | ConvertTo-Json -Depth 8
