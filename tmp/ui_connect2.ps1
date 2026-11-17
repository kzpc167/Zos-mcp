param([string]$Tab, [string]$Click, [switch]$Dump)

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)

foreach ($w in $wins) {
    if ($w.Current.Name -notmatch 'OpticStudio') { continue }
    Write-Output ("WINDOW: " + $w.Current.Name)

    if ($Tab) {
        $tcond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
        $tabs = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tcond)
        foreach ($t in $tabs) {
            if ($t.Current.Name -eq $Tab) {
                try {
                    $p = $t.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
                    $p.Select()
                    Write-Output ("TAB_SELECTED: " + $Tab)
                } catch {
                    try {
                        $tp = $t.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
                        $tp.Invoke()
                        Write-Output ("TAB_INVOKED: " + $Tab)
                    } catch { Write-Output ("TAB_FAIL: " + $_.Exception.Message) }
                }
                Start-Sleep -Milliseconds 700
            }
        }
    }

    $bcond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
    $btns = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $bcond)
    foreach ($b in $btns) {
        $n = $b.Current.Name
        if ([string]::IsNullOrWhiteSpace($n)) { continue }
        if ($Dump) { Write-Output ("  BTN: " + $n) }
        if ($Click -and $n -like $Click) {
            try {
                $p = $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
                $p.Invoke()
                Write-Output ("CLICKED: " + $n)
            } catch { Write-Output ("CLICK_FAIL: " + $n + " :: " + $_.Exception.Message) }
        }
    }
}
