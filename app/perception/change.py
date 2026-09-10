"""Structural environment drift and human-only blocker detection."""
from __future__ import annotations

from app.perception.models import EnvironmentChange, EnvironmentSnapshot


class VisualChangeDetector:
    def compare(self, before: EnvironmentSnapshot, after: EnvironmentSnapshot) -> tuple[EnvironmentChange, ...]:
        changes: list[EnvironmentChange] = []
        if before.active_application != after.active_application:
            changes.append(EnvironmentChange("application_changed", {"before": before.active_application,
                                                                      "after": after.active_application}))
        if before.browser_state.get("url") != after.browser_state.get("url"):
            changes.append(EnvironmentChange("navigation", {"before": before.browser_state.get("url"),
                                                             "after": after.browser_state.get("url")}))
        old = {item.element_id: item for item in before.visible_elements}
        new = {item.element_id: item for item in after.visible_elements}
        for key in new.keys() - old.keys():
            role = new[key].role.casefold()
            kind = "popup_appeared" if role in {"dialog", "alert", "popup"} else "ui_appeared"
            changes.append(EnvironmentChange(kind, {"element_id": key, "role": role}))
        for key in old.keys() - new.keys():
            changes.append(EnvironmentChange("ui_disappeared", {"element_id": key,
                                                                 "role": old[key].role}))
        return tuple(changes)


class HumanBlockerDetector:
    TERMS = {"captcha": "captcha", "two-factor": "mfa", "verification code": "mfa",
             "security key": "physical_security_key", "biometric": "biometric",
             "confirm payment": "payment_confirmation", "verify your identity": "identity_verification"}

    def detect(self, snapshot: EnvironmentSnapshot) -> tuple[EnvironmentChange, ...]:
        text = " ".join(f"{item.role} {item.label} {item.text}" for item in snapshot.visible_elements).casefold()
        return tuple(EnvironmentChange("human_required", {"blocker": blocker}, "critical")
                     for term, blocker in self.TERMS.items() if term in text)
