# Remote Webinar Capture Reference (`attend_webinar.py`)

Technical architecture, Chromium audio flags, and Zoom Events lifecycle notes for passive browser webinar attendance in Stage 0B.

---

## 1. Why Headless Chromium Cross-Tab Capture Beats OS Screen/Audio Grab

In agent shells on Windows, macOS, and Linux, traditional OS-level capture methods often fail:

- **`ffmpeg ddagrab` / `gdigrab`:** Frequently fails in non-interactive, locked, or isolated desktop sessions (`Desktop duplication access denied` or `Failed to capture image (error 5)`), and captures whatever windows happen to sit on screen.
- **OS speaker loopback (WASAPI / BlackHole / PulseAudio):** Requires playing webinar audio aloud through desktop speakers, mixes unrelated system notifications into the recording, and yields zero bytes if audio output is muted or idle.

`scripts/attend_webinar.py` avoids all of these failure modes by launching Playwright Chromium in `--headless=new` mode and capturing the target webinar tab directly inside the browser.

---

## 2. Privacy Lock (Camera and Microphone Hard-Disabled)

Before navigating to any webinar URL, `attend_webinar.py` enforces two independent layers of hardware isolation:

1. Creates the Playwright `BrowserContext` with `permissions=[]` (zero granted permissions).
2. Injects an init script (`BLOCK_CAMERA_MIC_JS`) into every page and frame that overrides `navigator.mediaDevices.getUserMedia` and legacy `navigator.getUserMedia` to reject immediately with `DOMException(..., "NotAllowedError")`.
3. Never clicks UI controls matching `Start Video`, `Unmute`, `Share Screen`, `Leave`, or `End Meeting`.

Always verify this lock on first setup via `--self-test` and confirm stdout reports `getUserMedia check: BLOCKED:NotAllowedError`.

---

## 3. Critical Chromium Audio Rule: Never Pass `--mute-audio`

Testing proved that launching Chromium with `--mute-audio` silences the `getDisplayMedia` `Tab audio` track completely (`Peak level dB: -inf`, `RMS level dB: -inf`), producing a silent recording.

- **Correct approach:** Omit `--mute-audio` from Chromium launch flags and instead pass `suppressLocalAudioPlayback: true` in the `getDisplayMedia` audio constraints:
  ```javascript
  audio: {
    suppressLocalAudioPlayback: true,
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: false
  }
  ```
- This mutes speaker playback on the host machine while delivering full `48 kHz` `128 kbps` Opus audio to `MediaRecorder` and the live WebAudio `AnalyserNode` RMS/Peak meter.

---

## 4. Cross-Tab Localhost Controller Architecture

Running `MediaRecorder` directly inside a third-party webinar page (such as Zoom) breaks for two reasons:
1. Strict Content Security Policy (CSP) headers block `fetch()` uploads to `127.0.0.1`.
2. Full-page redirects or new-tab switches destroy an in-page recorder.

`attend_webinar.py` solves both by running a lightweight local HTTP server on `127.0.0.1:<ephemeral_port>` and opening a dedicated controller tab (`/recorder`):
- Right before starting capture, Python temporarily sets `document.title = "WEBINAR_CAPTURE_TARGET"` on the active webinar tab, calls `window.startCapture(...)` on `/recorder` (auto-selected via Chromium's `--auto-select-tab-capture-source-by-title=WEBINAR_CAPTURE_TARGET` flag), and restores the original page title.
- `/recorder` posts 5-second WebM (`video/webm;codecs=vp8,opus`) chunks directly to `http://127.0.0.1:<port>/chunk?seg=N`, writing continuously to disk so long sessions never accumulate in browser RAM.
- Live audio RMS/Peak levels post every 3 seconds to `/telemetry` and are written to `<scratch_dir>/<slug>_status.json` alongside periodic `<scratch_dir>/<slug>_live.png` screenshots.

---

## 5. Zoom Events Lifecycle & Agent Supervision

Observed behavior on Zoom Events (`https://events.zoom.us/ej/...`):

1. **Pre-authenticated join links:** Unique `/ej/` links often authenticate straight into the Zoom Events Lobby (`https://events.zoom.us/ejl/.../home`) without triggering an email OTP or password login.
2. **Waiting-room open:** The lobby `Join` button and `Join methods` (`...`) menu remain disabled until roughly 5 minutes before the scheduled start time. `attend_webinar.py` polls safely, selects `Join methods -> Web`, and clicks `Join` once enabled.
3. **New-tab handoff:** Joining via Web opens the Zoom Workplace Web Client in a new browser tab. `attend_webinar.py` detects the `page` event, switches focus, attaches a fresh `MediaRecorder` segment to the new tab, and closes the stale lobby tab.
4. **End-of-webinar detection MUST run before modal dismissal:** When a host ends a Zoom Event, Zoom displays `"This webinar has been ended by host"` with an `OK` button and redirects to `/meeting/survey?sessionId=...`. Clicking `OK` dismisses the end message and leaves the recorder running on the silent survey page. `attend_webinar.py` checks both frame text (`"this webinar has been ended by host"`, `"post webinar survey"`, etc.) and URL patterns (`/meeting/survey`, `/postattendee`, `/wc/leave`) **before** dismissing benign interstitials, never clicks `OK` on end-session dialogs, and also falls back to sustained post-speech silence (`--end-silence-seconds 180`).
5. **Lossless silence trimming:** Because joining 5 minutes early captures waiting-room silence, `finalize_recordings()` runs `ffmpeg silencedetect=noise=-50dB:d=15` and losslessly (`-c copy`) trims leading waiting-room and trailing post-webinar silence (keeping `3s` lead-in and `4s` tail padding) unless `--no-auto-trim-silence` is set.
6. **Live agent command channel:** While running in the background, write a JSON file to `<scratch_dir>/<slug>_cmd.json` to trigger actions without restarting:
   - `{"action": "screenshot"}`
   - `{"action": "stop"}`
   - `{"action": "start_recording"}`
   - `{"action": "click_text", "text": "Join Audio by Computer"}`
   - `{"action": "click", "selector": "button.accept"}`
   - `{"action": "switch_page", "index": 1}`
   - `{"action": "dump_text"}`
