from run_dashboard import dashboard_token


def test_dashboard_generates_strong_per_run_token_when_unconfigured():
    first, generated = dashboard_token({})
    second, second_generated = dashboard_token({})
    assert generated and second_generated
    assert len(first) >= 16 and first != second


def test_dashboard_honors_valid_configured_token_and_rejects_short_value():
    configured = "owner-configured-token"
    assert dashboard_token({"BRAINLESS_DASHBOARD_TOKEN": configured}) == (configured, False)

    try:
        dashboard_token({"BRAINLESS_DASHBOARD_TOKEN": "short"})
    except ValueError as error:
        assert "at least 16" in str(error)
    else:
        raise AssertionError("short dashboard token was accepted")
