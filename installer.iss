; 旁白 Inno Setup 安装包脚本
; 使用方法: iscc installer.iss
; 输出: dist/旁白_Setup_v1.0.0.exe

#define MyAppName "旁白"
#define MyAppVersion "1.0.7"
#define MyAppPublisher "atvkh"
#define MyAppURL "https://github.com/atvkh/kuaishou-live-mate"
#define MyAppExeName "旁白.exe"

[Setup]
; 应用信息
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
; 安装目录
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; 安装包输出
OutputDir=dist
OutputBaseFilename=旁白_Setup_v{#MyAppVersion}
; 压缩
Compression=lzma2/ultra64
SolidCompression=yes
; 权限
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; 卸载
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
; 其他
DisableProgramGroupPage=yes
WizardStyle=modern
LanguageDetectionMethod=none

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce
Name: "startup"; Description: "开机自启动"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
; onedir 打包输出目录下所有文件
Source: "dist\旁白\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; 开始菜单快捷方式
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载{#MyAppName}"; Filename: "{uninstallexe}"
; 桌面快捷方式
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
; 开机自启
Name: "{autostartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
; 安装后可选启动程序
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动{#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理程序目录（用户数据在AppData，不受影响）
Type: filesandordirs; Name: "{app}"

[Code]
// 升级时先关闭正在运行的程序
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // 尝试关闭正在运行的旧版本
  Exec(ExpandConstant('taskkill'), '/f /im 旁白.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;
