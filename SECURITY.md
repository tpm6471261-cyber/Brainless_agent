# Security

No detector may harvest credentials or bypass UAC, Defender, firewall, lock screen, or credential prompts.
Keyboard and clipboard contents are not persisted by the core event system. Sensitive observation is off by
default. Destructive/system/security actions require explicit permissions and confirmation. `DRY_RUN` blocks
dangerous actions, and emergency stop independently blocks new actions while preserving history.

Process ID 0 through 4 is always treated as protected by the built-in termination action. The project never
auto-confirms UAC or credential prompts and never registers actions to weaken Defender, firewall, credentials,
or other Windows security controls. Clipboard events contain only type and length, never clipboard content.
