"""DB-only account checks; no HMI, sessions, user/job linking or device activity."""

import io
import json
import os
from uuid import uuid4

import pytest


@pytest.fixture
def connection():
    dsn=os.environ.get("HISTORY_TEST_DSN")
    if not dsn:
        pytest.skip("set HISTORY_TEST_DSN for PostgreSQL account checks")
    from history import store
    with store.connect(dsn) as conn:
        if not conn.execute("SELECT current_database() AS name").fetchone()["name"].endswith("_test"):
            pytest.fail("account tests require a separate _test database")
        store.initialize(conn)
        with conn.transaction(force_rollback=True):
            yield conn


def unique():
    return "fixture_"+uuid4().hex


def test_create_list_authenticate_and_duplicate_preserves_account(connection):
    from history import accounts
    username=unique()
    created=accounts.create_user(connection,username,"시험 사용자","fixture-password")
    assert set(created)=={"user_id","username","display_name","created_at"}
    assert created in accounts.list_users(connection)
    assert accounts.authenticate(connection,username,"fixture-password")==created
    assert accounts.authenticate(connection,username,"wrong-password") is None
    assert accounts.authenticate(connection,unique(),"fixture-password") is None
    before=connection.execute("SELECT password_hash FROM c2_history.users WHERE username=%s",(username,)).fetchone()
    assert before["password_hash"] != "fixture-password"
    with pytest.raises(ValueError,match="already exists"):
        accounts.create_user(connection,username,"다른 이름","different-password")
    assert connection.execute("SELECT password_hash FROM c2_history.users WHERE username=%s",(username,)).fetchone()==before
    assert accounts.authenticate(connection,username,"fixture-password")==created


@pytest.mark.parametrize("username,name", [("","시험"),(" x","시험"),("ok",""),("ok","시험\0")])
def test_invalid_identity_does_not_create_account(connection,username,name):
    from history import accounts
    with pytest.raises(ValueError):
        accounts.create_user(connection,username,name,"fixture-password")


def test_actual_transaction_failure_rolls_back_account(connection):
    from history import accounts
    username=unique()
    with pytest.raises(ZeroDivisionError):
        with connection.transaction():
            accounts.create_user(connection,username,"시험","fixture-password")
            raise ZeroDivisionError("fixture transaction interruption")
    assert accounts.authenticate(connection,username,"fixture-password") is None


def test_bound_identity_sql_injection_text_is_ordinary_data(connection):
    from history import accounts
    username=unique()+"'; SELECT 1; --"
    created=accounts.create_user(connection,username,"시험","fixture-password")
    assert accounts.authenticate(connection,username,"fixture-password")==created


def test_stored_corrupt_hash_is_not_silently_bad_credentials(connection):
    from history import accounts
    username=unique()
    accounts.create_user(connection,username,"시험","fixture-password")
    connection.execute("UPDATE c2_history.users SET password_hash=%s WHERE username=%s",("invalid",username))
    with pytest.raises(ValueError,match="stored password hash"):
        accounts.authenticate(connection,username,"fixture-password")


def test_cli_input_and_outputs_never_return_password_or_hash(connection,monkeypatch,capsys):
    from contextlib import nullcontext
    from history.__main__ import main
    monkeypatch.setattr("history.store.connect",lambda dsn: nullcontext(connection))
    username=unique()
    monkeypatch.setenv("HISTORY_DATABASE_DSN",os.environ["HISTORY_TEST_DSN"])
    monkeypatch.setattr("sys.stdin",io.StringIO("fixture-password\n"))
    assert main(["create-user",username,"시험","--password-stdin"])==0
    created=json.loads(capsys.readouterr().out)
    assert "password_hash" not in created
    monkeypatch.setattr("sys.stdin",io.StringIO("fixture-password\n"))
    assert main(["check-user",username,"--password-stdin"])==0
    assert json.loads(capsys.readouterr().out)==created
    monkeypatch.setattr("sys.stdin",io.StringIO("wrong-password\n"))
    assert main(["check-user",username,"--password-stdin"])==1
    output=capsys.readouterr()
    assert "invalid username or password" in output.err
    assert "password_hash" not in output.out and "wrong-password" not in output.err
    assert main(["users"])==0
    assert created in json.loads(capsys.readouterr().out)


def test_no_terminal_without_password_stdin_is_explicit_error(connection,monkeypatch,capsys):
    from history.__main__ import main
    monkeypatch.setenv("HISTORY_DATABASE_DSN",os.environ["HISTORY_TEST_DSN"])
    monkeypatch.setattr("sys.stdin",io.StringIO("ignored"))
    assert main(["create-user",unique(),"시험"])==1
    assert "requires a terminal" in capsys.readouterr().err
