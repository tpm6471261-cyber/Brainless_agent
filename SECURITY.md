# Security

No detector may harvest credentials or bypass UAC, Defender, firewall, lock screen, or credential prompts.
Keyboard and clipboard contents are not persisted by the core event system. Sensitive observation is off by
default. Destructive/system/security actions require explicit permissions and confirmation. `DRY_RUN` blocks
dangerous actions, and emergency stop independently blocks new actions while preserving history.
