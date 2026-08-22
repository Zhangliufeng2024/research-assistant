; Research Assistant Windows 安装程序（R6 计划交付物）。
;
; 用法：
;   1) python build.py                       ; 先产出 dist/ResearchAssistant/
;   2) ISCC packaging\installer.iss          ; 产出 dist/ResearchAssistant_setup_<ver>.exe
;
; 数据安全说明：会话、写作产物与 .env 全部存放在**用户自选的工作目录**，
; 不写入 {app}；卸载只移除程序文件，不触碰任何用户数据。

#define MyAppName "Research Assistant"
#define MyAppVersion "3.3.1"
#define MyAppPublisher "Zhangliufeng2024"
#define MyAppExeName "ResearchAssistant.exe"

[Setup]
; GUID 固定不变：同机升级安装识别为同一应用。
AppId={{7A3C9E41-5B2D-4F68-8A19-D04E23C7B5F6}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
LicenseFile=..\LICENSE
SetupIconFile=app_icon.ico
OutputDir=..\dist
OutputBaseFilename=ResearchAssistant_setup_{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 允许无管理员权限的按用户安装（UAC 弹窗可跳过，普通用户友好）
PrivilegesRequiredOverridesAllowed=dialog commandline

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\dist\ResearchAssistant\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent
