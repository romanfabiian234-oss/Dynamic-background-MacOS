# AI agent instructions — Dynamic Background for macOS

For code changes, reviews and tests, use the general [PerfectCode / SKILL.md](https://github.com/romanfabiian234-oss/PerfectCode.md/blob/main/SKILL.md) guidance **only if accessible**. It is a private optional reference; this link does not grant tools/permissions or replace local requirements. If inaccessible, proceed using this repository's rules without guessing.

## Project requirements
- Start from [README.md](README.md), existing code and the `tests/` suite; keep macOS-specific wallpaper behavior and user preferences compatible.
- Preserve data outside the source tree, avoid silently modifying the user's wallpapers or adding automatic login/background services.
- Respect the Pexels attribution constraints. Do not enable unattended Pexels image selection where attribution cannot be displayed as required by this project's documented design.
- Verify the affected path with suitable offline tests and, when available, a real macOS wallpaper test. State clearly when native behavior was not verified.
- Avoid unrelated refactors, hidden network calls, private key exposure and changes to other repositories.

Specific project constraints and higher-priority instructions override PerfectCode's generic advice.
