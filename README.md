# Orbit Tabs

**One launchpad for all your courses.**

Orbit Tabs opens Orbit Learning in its own browser tabs. It uses its own browser engine and works on computers with Chrome installed. Sign in inside Orbit Tabs the first time. The app keeps its own browser profile under your user account, so future launches can reuse the session until Orbit requires another sign-in.

## Windows x64

Extract `Orbit-Tabs-Windows-x64.zip` into a folder and double-click **Orbit Tabs.exe** inside it. Keep the extracted files together. The portable version includes Python and the browser engine. It runs without a browser extension or an administrator install. Your computer still needs to allow unsigned portable apps.

To run from source instead, install Python 3.10 or later with the Python launcher, then double-click `Start-Orbit-Tabs.cmd`. It installs the app dependencies if needed.

## macOS and Linux

Use a Python 3.10 or newer environment, install `python3 -m pip install -r requirements.txt`, then run `python3 orbit_embedded.py`. Linux needs a graphical desktop and the system libraries required by Qt WebEngine. To keep the sign-in encrypted between sessions, Linux also needs `secret-tool` (libsecret) and a running keyring such as GNOME Keyring or KWallet. The older `orbit_desktop.py` is the separate Firefox/Violentmonkey companion and is optional.

## Student license

On first launch, the embedded desktop app shows the full license, highlights the key terms during a 10-second countdown, and requires you to confirm eligibility and accept before opening Orbit. The acceptance is saved locally for that version of the license. To try the screen again without changing your acceptance, choose **Orbit → Review license**, or launch with `--review-license`.

The in-app acceptance screen applies to the desktop app. GitHub allows anyone to view and fork a public repository under its terms.

## Courses and timers

The **My Learning** tab is pinned inside the app. The app checks at startup, when you choose **Check now**, and weekly while idle. It also rechecks periodically while courses are queued. **Managed tabs** defaults to **All**, which opens every unfinished course one at a time. Enter a number to limit RAM use or enter 0 to switch back to **All**. Lowering the limit leaves existing tabs open. Opened course tabs are listed in **Course timers**. **Monitor wall** shows native question cards with choices, current selections, elapsed time, and a live browser thumbnail in the top-right of each card. Click the thumbnail to open the full course. It reads visible course content from the embedded page and same-origin frames. Use **Page previews** for raw browser thumbnails at one frame per second, six per page. The separate **Course timers** panel is available from the wall. The monitor pauses when you switch away, minimize, or hide the app. The grid adapts from one to three columns. Press **F9** to show or hide the workspace sidebar and **Ctrl+K** to find an open page. **Settings → Reduce motion and effects** disables page fades, question transitions, and tile shadows. The desktop starts in light mode. **Settings → Theme** includes Adwaita and Catppuccin Latte, Frappé, Macchiato, and Mocha. **Dark appearance** switches the Adwaita palette. **Settings → Accent color** offers Blue, Mint, Lilac, and Sunset. Use **Ctrl+1** for Monitor wall and **Ctrl+2** for My Learning. The app reopens manually closed managed tabs while they are unfinished and closes managed tabs when the catalog confirms they are no longer unfinished. Turn off **Open unfinished courses** to pause opening and reopening. Enable **Settings → Start at sign-in** to check after your desktop login.

The dashboard can stay in the tray where supported. The app's timers track elapsed open time. Orbit decides how much time to credit and when its Submit button becomes available.

On slides that expose a text reveal button or a recognizable text animation, use **Orbit → Reveal lesson text** (Ctrl+Shift+L), or the same action in Course QA. Orbit Tabs reports when it finds no supported reveal.

## Answers and timed activities

The **Quick Start** guide appears the first time you open the updated app and is available again from **Orbit → Quick Start**. Hosted AI suggestions are on by default. Turn them off in **Settings → Enable hosted AI suggestions**. Existing settings are respected. Open **Course QA** in a course tab. **Prepare answers** builds a reviewable multiple-choice plan. **Suggest & apply** gathers the readable questions on the current screen in the background and selects the suggested answers once the batch is ready. Questions without a confident suggestion stay unanswered. The optional hosted service needs no API key or local model and is subject to its availability and rate limits. Manual plans and all desktop features work with AI off. After you confirm, the hosted model receives visible questions and choices. If it is unsure, it can search question text on Wikipedia.

After reviewing the plan, choose **Add submit** to append the quiz's visible Submit button. Use **Set delay** for a custom delay or **Add 7h timer** for a new random delay from 7 hours to 7 hours 46 minutes each run. **Run plan** applies the answers, waits for both the delay and the quiz's enabled button, then submits. The plan runs in the open course tab and needs the app and computer to stay running. The panel explains whether it is waiting for AI, an Orbit Tabs delay, or a course control. Hover over a course’s activity badge on the monitor wall to see the current reason. **Finish now…** requests one-time **Dangerous permission** to run the current answer plan and skip the app’s delay. Orbit still controls when Submit becomes available, and the resulting attempt may be recorded sooner than you intended. Enable **Settings → Skip Orbit Tabs submit delay** to get the same one-time confirmation from **Run plan** when it contains a timed Submit step. This setting starts off and preserves the delay saved in the plan.

Use **Inspect** to identify other controls and edit the plan if needed. Plans can choose radio options, check boxes, fill text, select dropdowns, and click buttons. The browser uses the quiz's normal submission flow. Some lesson players keep several Submit buttons in the page at once. If Add submit finds more than one, use the course's visible Submit button. Direct requests are used for hosted AI and Wikipedia lookup.

## Cats

Miso the astronaut cat appears in the toolbar by default. Click Miso to send the mascot around the active tab title with a rainbow trail and a line from mission control. Reduce motion keeps Miso still. The **Cat cam** button opens the compact player, and the **Cats** menu can hide Miso or switch feeds. **Catflix** from RSPCA Isle of Wight and the **Street Cat feeder** play direct streams in the native video dock. Use the feed selector to switch, **Retry** to reconnect, or **Source** to visit the camera provider. The player is muted by default and disconnects when the dock or app is closed, hidden, or minimized. The Street Cat feed may go offline, and **meow.camera website** opens the provider’s website separately.

## Educational use and privacy

Orbit Tabs is an independent educational project for use with Orbit Learning. Use it only where you have permission and follow the platform's terms and your institution's rules, including rules about assessments and AI. A local test result does not establish that a use is authorized or that time will be credited.

The embedded browser keeps its session locally. When Orbit Tabs quits, the browser profile (sign-in and site data) is sealed into an AES-256-GCM vault, and cached course covers are stored as AES-256-GCM files. The key is held by Windows Data Protection, the macOS Keychain, or the Linux Secret Service, never in a readable file. If no keystore is available, covers stay in memory and any already unsealed profile stays unsealed. An encrypted-only profile requires the original key to reopen. **Settings → Data protection** shows which applies. Page resources are cached in memory only. The profile is readable on disk while the app is running, and an unexpected exit leaves it unsealed until the next normal quit. If you confirm an AI request, the selected quiz text and choices are sent to Pollinations AI, and uncertain question text may be sent to Wikipedia. Use this feature only when you are permitted to share that material with those services.

The original project code is covered by the [Orbit Tabs Student License](LICENSE.md). Third-party components keep their own licenses. The portable Windows bundle is built separately from the source repository.
