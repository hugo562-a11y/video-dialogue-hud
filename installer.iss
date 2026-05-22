; 影片對話 HUD 工具 — Inno Setup 安裝檔製作腳本
; 官方網站: https://jrsoftware.org/isdl.php

[Setup]
; 應用程式基本資訊
AppId={{E487C0BD-B8E5-46D9-8F7E-3184E59508C6}}
AppName=影片對話 HUD 工具
AppVersion=1.0.0
AppPublisher=Antigravity Pair Program
AppPublisherURL=https://github.com/google-deepmind
DefaultDirName={localappdata}\Programs\影片對話HUD工具
DefaultGroupName=影片對話 HUD 工具
DisableProgramGroupPage=yes

; 輸出設定
OutputDir=setup
OutputBaseFilename=影片對話HUD工具_Setup
SetupIconFile=talking.png
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; 語言設定 (繁體中文與英文)
[Languages]
Name: "chinesetraditional"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 打包 PyInstaller 編譯出來的整個 dist\影片對話HUD工具 資料夾
Source: "dist\影片對話HUD工具\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; 開始功能表捷徑
Name: "{group}\影片對話 HUD 工具"; Filename: "{app}\影片對話HUD工具.exe"
; 桌面捷徑
Name: "{autodesktop}\影片對話 HUD 工具"; Filename: "{app}\影片對話HUD工具.exe"; Tasks: desktopicon

[Run]
; 安裝完成後自動啟動選項
Filename: "{app}\影片對話HUD工具.exe"; Description: "{cm:LaunchProgram,影片對話 HUD 工具}"; Flags: nowait postinstall skipifsilent
