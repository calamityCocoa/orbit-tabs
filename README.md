# Orbit Tabs

Orbit Tabs opens Orbit Learning in its own browser tabs. It uses its own browser engine and works on computers with Chrome installed. Sign in inside Orbit Tabs the first time. The app keeps its own browser profile under your user account, so future launches can reuse the session until Orbit requires another sign-in.

## Windows x64

Extract `Orbit-Tabs-Windows-x64.zip` into a folder and double-click **Orbit Tabs.exe** inside it. Keep the extracted files together. The portable version includes Python and the browser engine. It runs without a browser extension or an administrator install. Your computer still needs to allow unsigned portable apps.

To run from source instead, install Python 3.10 or later with the Python launcher, then double-click `Start-Orbit-Tabs.cmd`. It installs the app dependencies if needed.

## macOS and Linux

Use a Python 3.10 or newer environment, install `python3 -m pip install -r requirements.txt`, then run `python3 orbit_embedded.py`. Linux needs a graphical desktop and the system libraries required by Qt WebEngine. The older `orbit_desktop.py` is the separate Firefox/Violentmonkey companion and is optional.

## Courses and timers

The **My Learning** tab is pinned inside the app. The app checks at startup, when you choose **Check now**, and weekly while idle. It also rechecks periodically while courses are queued. The default cap is two managed course tabs to reduce RAM use. Increase **Managed tabs** if you want more open at once. Opened course tabs are listed in **Course timers**. **Monitor wall** shows previews of the browser tabs at one frame per second, six per page. Only a tab answering questions appears in color. The monitor pauses when you switch away, minimize, or hide the app. The grid uses two columns in narrow windows and three when space allows. **Settings → Dark appearance** changes the desktop controls. Use **Ctrl+1** for Monitor wall and **Ctrl+2** for My Learning. The app reopens manually closed managed tabs while they are unfinished and closes managed tabs when the catalog confirms they are no longer unfinished. Turn off **Open unfinished courses** to pause opening and reopening. Enable **Settings → Start at sign-in** to check after your desktop login.

The dashboard can stay in the tray where supported. The app's timers track elapsed open time. Orbit decides how much time to credit and when its Submit button becomes available.

## Answers and timed activities

Select a course tab and click **AI suggestions** to build a reviewable multiple-choice answer plan. No API key is needed. After you confirm, the hosted model receives visible questions and choices. If it is unsure, it can search question text on Wikipedia.

After reviewing the plan, choose **Add submit** to append the quiz's visible Submit button. Use **Set delay** for a custom delay or **Add 7h timer** for a new random delay from 7 hours to 7 hours 46 minutes each run. **Run plan** applies the answers, waits for both the delay and the quiz's enabled button, then submits. The plan runs in the open course tab and needs the app and computer to stay running.

Use **Inspect** to identify other controls and edit the plan if needed. Plans can choose radio options, check boxes, fill text, select dropdowns, and click buttons. The browser uses the quiz's normal submission flow. Direct requests are used for hosted AI and Wikipedia lookup.

## Cats

**Cats → Add a cat** shows a small local mascot. **meow.camera** and **Kitten Rescue Cam** open in a separate tab inside the app. The camera tab unloads its webpage when the app is minimized or hidden or you switch to a different tab. Selecting the camera tab while the app is visible loads it again.

## Educational use and privacy

Orbit Tabs is an independent educational project for use with Orbit Learning. Use it only where you have permission and follow the platform's terms and your institution's rules, including rules about assessments and AI. A local test result does not establish that a use is authorized or that time will be credited.

The embedded browser keeps its session locally. If you confirm an AI request, the selected quiz text and choices are sent to Pollinations AI, and uncertain question text may be sent to Wikipedia. Use this feature only when you are permitted to share that material with those services.

The original project code is covered by the [Orbit Tabs Student License](LICENSE.md). Third-party components keep their own licenses. The portable Windows bundle is built separately from the source repository.
