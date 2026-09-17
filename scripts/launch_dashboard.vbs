Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\.."
shell.Run """" & shell.CurrentDirectory & "\scripts\run_dashboard_detached.cmd" & """", 0, False
