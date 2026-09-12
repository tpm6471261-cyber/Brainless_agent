from app.main import CLI_ADVISORY_NOTICE, format_cli_result


def test_cli_result_is_explicitly_advisory() -> None:
    result = format_cli_result("Draft complete")

    assert "no external action was executed" in result
    assert result.endswith("Draft complete")
    assert "require confirmation before external actions" in CLI_ADVISORY_NOTICE
