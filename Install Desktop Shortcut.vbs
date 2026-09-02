' One-time setup: creates a desktop shortcut to Start EIVANTA Dashboard.bat.
' Double-click this file once. After that, use the desktop icon instead.

Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
targetBat = appDir & "\Start EIVANTA Dashboard.bat"
desktopDir = WshShell.SpecialFolders("Desktop")
shortcutPath = desktopDir & "\EIVANTA Dashboard.lnk"

If Not fso.FileExists(targetBat) Then
    MsgBox "Could not find '" & targetBat & "'." & vbCrLf & _
           "Make sure this script is still inside the Sports_Betting_App folder.", vbCritical, "Setup failed"
    WScript.Quit 1
End If

Set link = WshShell.CreateShortcut(shortcutPath)
link.TargetPath = targetBat
link.WorkingDirectory = appDir
link.WindowStyle = 1 'normal window, so first-run errors are visible
link.Description = "Launch the EIVANTA Analytics Terminal (backend + dashboard)"
link.Save

MsgBox "Desktop shortcut created: 'EIVANTA Dashboard'." & vbCrLf & _
       "Double-click it any time to start the app.", vbInformation, "Setup complete"
