param([switch]$Dump, [string]$Click)

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)

foreach ($w in $wins) {
    $name = $w.Current.Name
    if ($name -notmatch 'OpticStudio|Zemax') { continue }
    Write-Output "WINDOW: $name"
    $bcond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
    $btns = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $bcond)
    foreach ($b in $btns) {
        $n = $b.Current.Name
        if ([string]::IsNullOrWhiteSpace($n)) { continue }
        Write-Output ("  BTN: {0} | id={1}" -f $n, $b.Current.AutomationId)
        if ($Click -and $n -eq $Click) {
            try {
                $p = $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
                $p.Invoke()
                Write-Output ("  CLICKED: {0}" -f $n)
            } catch {
                Write-Output ("  CLICK_FAIL: {0}" -f $_.Exception.Message)
            }
        }
    }
    # list tabs too
    $tcond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
    $tabs = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tcond)
    foreach ($t in $tabs) { Write-Output ("  TAB: {0}" -f $t.Current.Name) }
}
