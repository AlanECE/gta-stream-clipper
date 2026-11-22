; L'installeur Windows de GTA Stream Clipper (Inno Setup 6.7).
;   python build_exe.py      (le construit après l'application, si Inno Setup 6 est installé)
; ou à la main : ISCC.exe /DAppVersion=1.4.0 packaging\installer.iss
;
; Sans droits administrateur : l'application s'installe dans le dossier de l'utilisateur, avec une icône sur le
; Bureau et dans le menu Démarrer. Après la copie des fichiers, un tuto en 4 écrans montre comment s'en servir.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "GTA Stream Clipper"
#define AppExe "GTA-Stream-Clipper.exe"
#define Repo "https://github.com/AlanECE/gta-stream-clipper"
#include "tuto\dims.iss"

[Setup]
AppId={{6E2C9A41-3B7D-4F15-A8C2-91D47E5B0F3A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=iAlan
AppPublisherURL={#Repo}
AppSupportURL={#Repo}/issues
AppUpdatesURL={#Repo}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=GTA-Stream-Clipper-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern dynamic
WizardSizePercent=150
WizardImageFile=wizard-100.png,wizard-125.png,wizard-150.png,wizard-200.png,wizard-250.png
WizardSmallImageFile=wizard-small-100.png,wizard-small-125.png,wizard-small-150.png,wizard-small-200.png,wizard-small-250.png
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany=iAlan
VersionInfoDescription=Installation de {#AppName}

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Messages]
fr.WelcomeLabel1=Bienvenue dans GTA Stream Clipper
fr.WelcomeLabel2=L'application gratuite qui transforme les streams GTA 6 en clips verticaux prêts à poster : webcam en haut, jeu en dessous, titre et sous-titres.%n%nL'installation prend une minute. Ensuite, un petit tuto en 4 écrans te montre où cliquer.%n%nClique sur « Installer ».
fr.FinishedHeadingLabel=C'est prêt !
fr.FinishedLabel=GTA Stream Clipper est installé : son icône est sur ton Bureau.%n%nAu lancement, une fenêtre noire s'ouvre et l'interface s'affiche dans ton navigateur. Laisse la fenêtre noire ouverte : c'est elle qui fait tourner l'application (la fermer arrête tout).%n%nTes clips sont rangés dans Vidéos\GTA Stream Clipper.
fr.FinishedLabelNoIcons=GTA Stream Clipper est installé.
fr.ClickFinish=Clique sur Terminer.
fr.ClickNext=

[Files]
Source: "..\dist\GTA-Stream-Clipper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "tuto\tuto1.png"; Flags: dontcopy
Source: "tuto\tuto2.png"; Flags: dontcopy
Source: "tuto\tuto3.png"; Flags: dontcopy
Source: "tuto\tuto4.png"; Flags: dontcopy

[InstallDelete]
; une mise à jour repart d'un dossier propre (pas de fichiers d'une ancienne version qui traînent)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Comment: "Les streams GTA 6 en clips verticaux"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Comment: "Les streams GTA 6 en clips verticaux"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Lancer GTA Stream Clipper"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
#ifndef SHOTS
; le modèle de transcription et les emojis téléchargés (tes clips, eux, restent dans Vidéos)
Type: filesandordirs; Name: "{localappdata}\gta-stream-clipper"
#endif

[Code]
{ Une page du tuto : la capture la plus grande possible, et une ou deux phrases dessous. }
function AddTuto(AfterID: Integer; Caption, Desc, ImageFile: String; ImgW, ImgH: Integer; Text: String): Integer;
var
  Page: TWizardPage;
  Img: TBitmapImage;
  Lbl: TNewStaticText;
  Avail, W, H: Integer;
begin
  Page := CreateCustomPage(AfterID, Caption, Desc);
  ExtractTemporaryFile(ImageFile);
  Img := TBitmapImage.Create(Page);
  Img.Parent := Page.Surface;
  Img.Stretch := True;
  Img.PngImage.LoadFromFile(ExpandConstant('{tmp}\') + ImageFile);
  { la place pour le texte : deux lignes }
  Avail := Page.SurfaceHeight - ScaleY(52);
  W := Page.SurfaceWidth;
  H := W * ImgH div ImgW;
  if H > Avail then begin
    H := Avail;
    W := H * ImgW div ImgH;
  end;
  Img.Width := W;
  Img.Height := H;
  Img.Left := (Page.SurfaceWidth - W) div 2;
  Img.Top := 0;

  Lbl := TNewStaticText.Create(Page);
  Lbl.Parent := Page.Surface;
  Lbl.AutoSize := False;
  Lbl.WordWrap := True;
  Lbl.Left := 0;
  Lbl.Width := Page.SurfaceWidth;
  Lbl.Top := H + ScaleY(10);
  Lbl.Height := Page.SurfaceHeight - Lbl.Top;
  Lbl.Caption := Text;
  Lbl.Font.Size := 10;
  Result := Page.ID;
end;

#ifdef SHOTS
{ Version de contrôle (ISCC /DSHOTS, jamais publiée) : l'assistant avance tout seul toutes les 3 secondes pour que
  chaque page puisse être capturée et relue. À la fin, rien n'est lancé. }
function SetTimer(hWnd: LongWord; nIDEvent, uElapse: LongWord; lpTimerFunc: LongWord): LongWord;
  external 'SetTimer@user32.dll stdcall';

var
  ShotPage: Integer;

procedure ShotTick(H: LongWord; Msg: LongWord; IdEvent: LongWord; Time: LongWord);
var
  I: Integer;
begin
  { chaque page reste affichée au moins un tour complet avant d'être passée }
  if WizardForm.CurPageID <> ShotPage then begin
    ShotPage := WizardForm.CurPageID;
    Exit;
  end;
  if WizardForm.CurPageID = wpFinished then
    for I := 0 to WizardForm.RunList.Items.Count - 1 do
      WizardForm.RunList.Checked[I] := False;
  if WizardForm.NextButton.Visible and WizardForm.NextButton.Enabled then
    WizardForm.NextButton.OnClick(WizardForm.NextButton);
end;
#endif

{ la page d'accueil est la dernière avant la copie des fichiers : son bouton dit « Installer » }
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpWelcome then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall);
end;

procedure InitializeWizard;
var
  ID: Integer;
begin
#ifdef SHOTS
  SetTimer(0, 0, 2500, CreateCallback(@ShotTick));
#endif
  ID := AddTuto(wpInstalling, 'Comment ça marche · 1 sur 4', 'Les clips viraux : les moments qui ont déjà fait le buzz',
    'tuto1.png', {#Tuto1W}, {#Tuto1H},
    '1. Choisis la langue et la période, puis « Rechercher ».   2. Clique sur un clip pour le regarder.');
  ID := AddTuto(ID, 'Comment ça marche · 2 sur 4', 'Crée le clip vertical',
    'tuto2.png', {#Tuto2W}, {#Tuto2H},
    '3. Écris ton titre si tu veux, choisis le style des sous-titres, puis « Créer le clip vertical ». Il arrive dans la Bibliothèque en 20 à 40 secondes (la toute première fois, compte quelques minutes).');
  ID := AddTuto(ID, 'Comment ça marche · 3 sur 4', 'Rallonge, corrige, puis télécharge (onglet Bibliothèque)',
    'tuto3.png', {#Tuto3W}, {#Tuto3H},
    '1 et 2. Fais glisser les poignées jaunes : le clip commence plus tôt, finit plus tard. Titre, style et mots se corrigent plus bas. 3. « Mettre à jour l''aperçu ».  4. « Télécharger le MP4 ».');
  ID := AddTuto(ID, 'Comment ça marche · 4 sur 4', 'Un stream entier, ou un live',
    'tuto4.png', {#Tuto4W}, {#Tuto4H},
    '« Depuis un lien » : colle une rediffusion Twitch ou Kick. « En direct » : choisis un live, l''application le regarde et clippe toute seule. Coche « Veille » pour attendre le prochain live d''un streameur.');
end;
