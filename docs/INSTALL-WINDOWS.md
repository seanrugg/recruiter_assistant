# Installing Recruiting Desk on Windows

About five minutes. You do not need to be an administrator on the computer.

## 1. Download

Go to the **[latest release](../../../releases/latest)** and click
**`RecruitingDesk-Setup-x.y.z.exe`** under *Assets*. It saves to your
Downloads folder.

## 2. Run the installer

Double-click the file you downloaded.

### If Windows says "Windows protected your PC"

This is expected, and it will happen for every small, independent program until
it has been downloaded enough times for Microsoft to recognize it. It does not
mean anything is wrong with the file.

1. Click **More info**.
2. Check that the app name says **RecruitingDesk-Setup**.
3. Click **Run anyway**.

If you would rather confirm the file first, see
[Checking the download](#checking-the-download) below.

### Then

1. Choose whether you want a desktop shortcut.
2. Click **Install**.
3. Leave **Open Recruiting Desk now** ticked and click **Finish**.

Your web browser opens to Recruiting Desk. That is the app — it runs on your
computer and shows up in the browser. The address will start with
`http://127.0.0.1`, which means "this computer." Nothing is on the internet.

## 3. First-time setup

On the **Start here** tab:

1. Choose **Softball** or **Baseball** and click **Start**.
2. **Paste the player's GameChanger profile link** (it looks like
   `web.gc.com/athlete/...`). Tick the details it finds and click
   **Use the ticked ones**, then tick which seasons' stats to use and click
   **Add ticked seasons to the stat line**. The profile has to be published in
   the GameChanger app.
3. Open **Settings** (top right) and choose which AI writes the drafts. Read the
   note about where information goes before you pick.

The checklist on **Start here** shows what is left.

## Opening it again later

Start menu → **Recruiting Desk**, or the desktop shortcut.

The app keeps running quietly in the background after you close the browser
tab, so the next time opens instantly. To turn it off completely:
**Settings → Quit Recruiting Desk**.

## Updating

Download the newer installer from the
[releases page](../../../releases/latest) and run it. Your player's information is
kept.

## Uninstalling

**Settings → Apps → Installed apps → Recruiting Desk → Uninstall.**

This removes the app but **keeps** your player's information, in case you
reinstall. To remove that too, delete this folder:

```
%APPDATA%\RecruitingDesk
```

(Paste that into the File Explorer address bar to open it.)

## Something not working?

| What you see | What to do |
|---|---|
| The browser opens but says the page can't be reached | Wait five seconds and refresh. The first start takes a moment. |
| Nothing happens when you open it | It may already be running. Open your browser and go to `http://127.0.0.1:8770` |
| Your antivirus quarantined it | Restore it from quarantine and mark it as allowed. Programs built this way are sometimes flagged by mistake. [Report it](../../../issues) so we can submit it for review. |
| "Writing needs your permission" or an AI error | Open **Settings**, check the AI choice and key, and click **Test it**. |
| Anything else | [Open an issue](../../../issues/new/choose) and describe what happened. Please do not include your player's personal details. |

## Checking the download

Each release has a `.sha256` file next to the installer. In PowerShell:

```powershell
Get-FileHash "$env:USERPROFILE\Downloads\RecruitingDesk-Setup-x.y.z.exe" -Algorithm SHA256
```

The long code it prints should match the one in the `.sha256` file.
