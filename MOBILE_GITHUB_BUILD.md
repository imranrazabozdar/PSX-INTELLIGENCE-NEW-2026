# Mobile-only APK build

This repository already contains the GitHub Actions workflow needed to compile the Android APK.

## Recommended Android method: Termux + Git

1. Install **Termux** from F-Droid (the Play Store build is often outdated).
2. Extract this ZIP on your phone. Keep the folder structure intact, including the hidden `.github` folder.
3. In Termux run:

```bash
pkg update
pkg install git
termux-setup-storage
```

4. Open your GitHub repository in Chrome and copy its HTTPS URL. It will look like:

```text
https://github.com/YOUR-USERNAME/PSX-APK.git
```

5. In Termux, go to the extracted folder. Example:

```bash
cd /storage/emulated/0/Download/psx_v2_github_ready
```

6. Then run:

```bash
git init
git branch -M main
git add .
git commit -m "PSX Intelligence V2 Alpha"
git remote add origin https://github.com/YOUR-USERNAME/PSX-APK.git
git push -u origin main
```

If GitHub asks for a password, use a GitHub Personal Access Token instead of your account password.

## Build APK on GitHub

After the files appear in GitHub:

1. Open your repository.
2. Tap **Actions**.
3. Tap **Build PSX Intelligence APK**.
4. Tap **Run workflow** if a build has not already started automatically.
5. Wait for the green check mark.
6. Open the completed workflow run.
7. Scroll to **Artifacts**.
8. Download **PSX-Intelligence-V2-Alpha-APK**.
9. Extract the downloaded artifact ZIP.
10. Tap `PSX-Intelligence-V2-Alpha.apk` and install it.

Android may ask you to allow **Install unknown apps** for Chrome or your Files app.
