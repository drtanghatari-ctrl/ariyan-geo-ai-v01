# Getting ARIYAN GEO AI onto your phone — no Android Studio needed

This builds the app on GitHub's own servers and hands you a finished
.apk file to install — you never install any Android tooling on your
PC.

## 1. Extract the project

Right-click `ARIYAN_GEO_AI_Android_vslice.zip` → **Extract All** (built
into Windows, no new software). You should end up with a folder called
`ARIYAN_GEO_AI` containing `app/`, `gradle/`, `build.gradle.kts`, etc.

## 2. Create a new GitHub repository

1. Go to **github.com/new**.
2. Give it any name (e.g. `ariyan-geo-ai`). Public or Private both work.
3. Leave everything else default, click **Create repository**.

## 3. Upload the project

On the new (empty) repo's page, GitHub shows a line like *"...or
uploading an existing file"* — click that link.

Drag the whole extracted **`ARIYAN_GEO_AI` folder** (the one from step
1) onto the upload area. GitHub preserves the folder structure. Scroll
down and click **Commit changes**.

## 4. Watch it build

Click the **Actions** tab at the top of the repo. You should see a
workflow run start within a few seconds (it's called "Build debug
APK"). Click into it to watch progress.

- **First run takes ~5-8 minutes** (downloading Gradle, the Android
  SDK pieces, and Chaquopy's Python+numpy build for Android).
- A green checkmark means it succeeded. A red X means something
  failed — click into the failed step to see the actual error, and
  share that with me if it happens; the message will usually say
  exactly what went wrong.

## 5. Download the APK

Once it's green, stay on that same run's page and scroll down to the
**Artifacts** section at the bottom. Click
**ariyan-geo-ai-debug-apk** to download a small zip. Extract it — inside
is `app-debug.apk`.

## 6. Get it onto your phone and install it

Any of these work — pick whichever is easiest for you:
- Email the .apk to yourself as an attachment, open the email on your
  phone, tap the attachment.
- Upload it to Google Drive (or similar), open the Drive app on your
  phone, tap the file.
- Plug your phone into the PC via USB and copy the file over directly
  (e.g. into the Downloads folder), then open it from your phone's
  Files app.

When you tap the .apk file on your phone, Android will likely ask to
allow installing from that source (whichever app you opened it with —
Gmail, Drive, Files). Allow it, then tap **Install**.

That's it — no Android Studio, no SDK, no command line, on your device
at all.

## If the build fails

Copy the error text from the failed red step in the Actions log and
send it over — the whole point of building this way is that the exact
failure is visible and shareable, rather than buried in a local
install that only you can see.
