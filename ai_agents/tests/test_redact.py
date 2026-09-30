from orchestrator.redact import redact_payload


def test_blocklisted_key_redacted() -> None:
    result = redact_payload({"license_number": "DL1234", "name": "Jane"})
    assert result == {"license_number": "[REDACTED]", "name": "Jane"}


def test_case_insensitive_key_match() -> None:
    result = redact_payload({"License_Number": "DL1234"})
    assert result == {"License_Number": "[REDACTED]"}


def test_nested_dict_redacted() -> None:
    result = redact_payload({"driver": {"phone_number": "555-0100", "name": "Jane"}})
    assert result == {"driver": {"phone_number": "[REDACTED]", "name": "Jane"}}


def test_list_of_dicts_redacted() -> None:
    result = redact_payload([{"image_bytes": b"..."}, {"name": "ok"}])
    assert result == [{"image_bytes": "[REDACTED]"}, {"name": "ok"}]


def test_token_redacted() -> None:
    result = redact_payload({"token": "eyJhbGciOi...", "role": "admin"})
    assert result == {"token": "[REDACTED]", "role": "admin"}


def test_non_blocklisted_fields_pass_through() -> None:
    result = redact_payload({"vehicle_plate": "ABC-123", "qty": 5})
    assert result == {"vehicle_plate": "ABC-123", "qty": 5}


def test_scalar_passes_through() -> None:
    assert redact_payload("plain string") == "plain string"
    assert redact_payload(42) == 42
    assert redact_payload(None) is None


def test_does_not_mutate_input() -> None:
    original = {"license_number": "DL1234"}
    redact_payload(original)
    assert original == {"license_number": "DL1234"}


def test_document_text_and_image_bytes_redacted() -> None:
    result = redact_payload({"document_text": "some ocr'd text", "image_bytes": b"binary"})
    assert result == {"document_text": "[REDACTED]", "image_bytes": "[REDACTED]"}


def test_backend_field_names_and_credentials_are_redacted() -> None:
    from orchestrator.redact import redact_payload

    raw = {
        "created_record": {"full_name": "Jane", "phone": "+923001234567", "license_number": "LIC-1"},
        "headers": {"Authorization": "Bearer abc"},
        "password": "hunter2",
        "_pending_image_bytes": b"\xff\xd8",
    }
    redacted = redact_payload(raw)
    assert redacted["created_record"] == {"full_name": "Jane", "phone": "[REDACTED]", "license_number": "[REDACTED]"}
    assert redacted["headers"]["Authorization"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["_pending_image_bytes"] == "[REDACTED]"
    assert raw["created_record"]["phone"] == "+923001234567"  # input untouched
