# ChipLoom visual assets

`chiploom-explainer-card.svg` sits above the Copper Skies card in the README: the last frame of the owner's explainer video (`docs/listen/media/chiploom-explainer.mp4`, 1:42, re-encoded at 720p to stay under 10 MB) with a play button. It links to the video in the listening room, because GitHub does not play a video stored in the repository inside a README.

`copper-skies-card.svg` is the listening card at the top of the README: the Copper Skies title, a play button and the song's waveform (120 RMS bars of the libopenmpt render) with an SMIL playhead that crosses it in the song's 1:42. It links to the listening room, because GitHub does not play audio inside a README. It is generated text, not a capture.

`chiploom-desktop-08.png`, `chiploom-agent-tab.png` and `chiploom-browser-studio.png` are the current README screenshots (version 0.8.1). The two window captures were rendered by Qt at 1680×1000 from the Windows window (Violet theme, English controls, Segoe UI); the browser studio was captured at 1440×900 by headless Microsoft Edge from `chiploom live serve --web`. They show Pixel Rush arranged on eight channels for the screenshots (channels 5 to 8 repeat channels 1 to 4 three rows later at volume 20), with an agent edit, a proposal and a take sent through the live API. Only the published example song appears.

`chiploom-desktop-library.png` is the 0.6 README screenshot, captured from the native Windows window with English controls and the Violet theme. It shows the bottom sample bank browser: search, type/role filters, compatibility, a waveform, note-based audition and insertion, below the full-width tracker. The displayed bank and Pocket Signals V2 test music remain local; neither is included as audio or project data.

`chiploom-desktop-v052.png` records the previous Windows layout, version 0.5.2, with October Letters playing in the Violet theme and English controls. Song settings, audio exports and the stereo meter sit above the full-width tracker.

`chiploom-desktop-v051.png` is a capture of the running Windows application, version 0.5.1, with October Letters playing in the Violet theme and English controls. It shows the integrated logo, simplified sidebar and live stereo meter. It records the previous sidebar layout.

`chiploom-desktop.png` is an unmodified screenshot supplied by the project owner for the public README. It shows the Windows desktop, October Letters, the Violet theme and English controls.

`chiploom-logo.png` is the approved header logo. It is an RGBA PNG with genuine transparent pixels, intended to read on light and dark backgrounds. The original generated alpha channel is preserved.

An identical copy is bundled under `tracker4agents/assets/` for installed desktop applications. The window icon displays only the four-channel emblem from this artwork, with transparent square padding at native icon sizes.

Created with the built-in image generation tool using the `imagegen` skill.

Design brief (summary): a compact horizontal logo, with four tracker columns woven into a stepped waveform beside the ChipLoom wordmark. Retro demoscene typography, teal and violet accents, legibility on light and dark backgrounds, and a genuine transparent background.
