# Event permissions

Observation scopes are separate from controls: `mouse.observe`, `keyboard.observe`, `screen.observe`,
`clipboard.read`, `filesystem.read`, `process.observe`, `window.observe`, `browser.observe`,
`network.observe`, `device.observe`, `audio.observe`, `system.observe`, `security.observe`.
Controls use the corresponding `.control`, `.write`, `.delete`, `.capture`, or `power.control` permission.
Subscriptions do not grant permissions; action execution checks the caller's current permission set.

`PERMISSIONS` is the canonical capability catalog and `permission_for_event(category)` supplies the minimum
observation permission for detector/agent factories. A child can receive only a subset of its parent's
permissions. Directory and application allow-lists add a second boundary around filesystem and process
actions; they never broaden the permission grant.
