import unittest

from survival import protocol


def command_record() -> dict:
    return {
        "schema_version": 1,
        "request_id": "telegram-91",
        "telegram_update_id": 91,
        "telegram_user_id": 42,
        "command": "restart",
        "received_at": "2026-09-04T00:00:00+00:00",
    }


def test_only_exact_uppercase_command_is_literal():
    assert protocol.parse_literal_command("RESTART") == "restart"
    assert protocol.parse_literal_command("RESET") == "reset"
    for text in ("restart", " RESTART", "RESTART ", "RESTART now", "/RESTART"):
        assert protocol.parse_literal_command(text) is None


def test_protocol_round_trips_exact_command_record():
    command = command_record()
    assert protocol.decode_command(protocol.encode_command(command)) == command


def test_protocol_rejects_extra_fields():
    payload = b'{"schema_version":1,"command":"restart","unit":"ssh.service"}'
    with unittest.TestCase().assertRaisesRegex(ValueError, "fields"):
        protocol.decode_command(payload)


def test_protocol_encoder_rejects_extra_fields():
    command = command_record() | {"unit": "ssh.service"}
    with unittest.TestCase().assertRaisesRegex(ValueError, "fields"):
        protocol.encode_command(command)


def test_protocol_rejects_unknown_command_value():
    command = command_record() | {"command": "status"}
    with unittest.TestCase().assertRaisesRegex(ValueError, "value"):
        protocol.decode_command(
            b'{"schema_version":1,"request_id":"telegram-91",'
            b'"telegram_update_id":91,"telegram_user_id":42,'
            b'"command":"status","received_at":"2026-09-04T00:00:00+00:00"}'
        )


def test_protocol_rejects_boolean_schema_version():
    command = command_record() | {"schema_version": True}
    with unittest.TestCase().assertRaisesRegex(ValueError, "value"):
        protocol.encode_command(command)


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
