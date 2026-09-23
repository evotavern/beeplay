# Agent notes

## UX check

We want no known user-facing bug to go unnoticed. When you work in this repo,
run the check first; it does nothing if someone ran it in the last hour:

```bash
ssh evotavern beeplay-ops ux --every 60
```

It lists what players ran into since the last check, by area and browser.
Game creation and gameplay are in scope, including anything that fails only in
in-app browsers (WeChat, QQ, Douyin). Everything else is only counted. How the
command works: `deploy/README.md`, "Operating the event".

Tell the user what it found. How findings get fixed is not decided yet.
