# Event permissions

Observation scopes are separate from controls: `mouse.observe`, `keyboard.observe`, `screen.observe`,
`clipboard.read`, `filesystem.read`, `process.observe`, `window.observe`, `browser.observe`,
`network.observe`, `device.observe`, `audio.observe`, `system.observe`, `security.observe`.
Controls use the corresponding `.control`, `.write`, `.delete`, `.capture`, or `power.control` permission.
Subscriptions do not grant permissions; action execution checks the caller's current permission set.
