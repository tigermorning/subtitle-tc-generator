param([int]$ProcId, [string]$ClassPart = "SysListView32", [string]$Seq = "", [string]$Out = "", [string]$ClickText = "")
# 마우스·포커스를 쓰지 않는다: 클래스 이름으로 SE 자식 창을 찾아 WM_KEYDOWN/UP을 보내고, PrintWindow로 캡처한다
# Seq 예: "DOWN*3,UP" (키 이름은 VK 표에서)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class K32 {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc f, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  public static IntPtr FindText(IntPtr parent, string text) {
    IntPtr found = IntPtr.Zero;
    EnumChildWindows(parent, (h, l) => { var sb = new StringBuilder(256); GetWindowText(h, sb, 256);
      if (sb.ToString() == text) { found = h; return false; } return true; }, IntPtr.Zero);
    return found;
  }
  public static List<IntPtr> Find(IntPtr parent, string part) {
    var res = new List<IntPtr>();
    EnumChildWindows(parent, (h, l) => { var sb = new StringBuilder(256); GetClassName(h, sb, 256);
      if (sb.ToString().Contains(part) && IsWindowVisible(h)) res.Add(h); return true; }, IntPtr.Zero);
    return res;
  }
}
"@
[K32]::SetProcessDPIAware() | Out-Null
$h = (Get-Process -Id $ProcId).MainWindowHandle
$VK = @{ DOWN = 0x28; UP = 0x26; HOME = 0x24; END = 0x23; PGDN = 0x22; PGUP = 0x21; RETURN = 0x0D }
if ($Seq) {
  $targets = [K32]::Find($h, $ClassPart)
  "찾은 창 $($targets.Count)"
  $t = $targets[0]
  foreach ($part in $Seq.Split(",")) {
    $name, $cnt = $part.Split("*"); if (-not $cnt) { $cnt = 1 }
    for ($i = 0; $i -lt [int]$cnt; $i++) {
      [K32]::PostMessage($t, 0x100, [IntPtr]$VK[$name], [IntPtr]1) | Out-Null
      [K32]::PostMessage($t, 0x101, [IntPtr]$VK[$name], [IntPtr]0xC0000001) | Out-Null
      Start-Sleep -Milliseconds 150
    }
  }
  Start-Sleep -Milliseconds 1500
}
if ($ClickText) {
  $b = [K32]::FindText($h, $ClickText)
  if ($b -eq [IntPtr]::Zero) { throw "button not found" }
  [K32]::SendMessage($b, 0xF5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null   # BM_CLICK
  Start-Sleep -Milliseconds 1500
}
if ($Out) {
  $r = New-Object K32+RECT; [K32]::GetWindowRect($h, [ref]$r) | Out-Null
  $bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $dc = $g.GetHdc(); [K32]::PrintWindow($h, $dc, 2) | Out-Null; $g.ReleaseHdc($dc)
  $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png); "saved"
}
