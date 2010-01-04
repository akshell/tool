[Setup]
AppName=Akshell
AppVerName=Akshell 0.1
DefaultDirName={pf}\Akshell
LicenseFile=LICENSE

[Files]
Source: "dist\*"; Excludes: "*.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\script.exe"; DestDir: "{app}"; DestName: "akshell.exe"; Flags: ignoreversion
Source: "setup.cmd"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "{app}\setup.cmd"; Parameters: """{sys}\akshell.cmd"" ""{app}"" ""{app}\akshell.exe"""

[UninstallDelete]
Type: files; Name: "{sys}\akshell.cmd"
