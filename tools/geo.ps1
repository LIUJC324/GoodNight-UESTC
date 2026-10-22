param()

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Devices.Geolocation.Geolocator, Windows.Devices.Geolocation, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($task, $type) {
    $asTask = $asTaskGeneric.MakeGenericMethod($type)
    $netTask = $asTask.Invoke($null, @($task))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

$access = Await ([Windows.Devices.Geolocation.Geolocator]::RequestAccessAsync()) ([Windows.Devices.Geolocation.GeolocationAccessStatus])
Write-Output "access: $access"

$locator = New-Object Windows.Devices.Geolocation.Geolocator
$locator.DesiredAccuracyInMeters = 100
try {
    $pos = Await ($locator.GetGeopositionAsync()) ([Windows.Devices.Geolocation.Geoposition])
    $p = $pos.Coordinate.Point.Position
    Write-Output ("lat: {0:N6}" -f $p.Latitude)
    Write-Output ("lon: {0:N6}" -f $p.Longitude)
    Write-Output ("accuracy: {0:N0} m" -f $pos.Coordinate.Accuracy)
} catch {
    Write-Output ("error: " + $_.Exception.Message)
}
