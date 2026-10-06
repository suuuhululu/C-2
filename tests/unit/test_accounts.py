import pytest

from history.accounts import hash_password, verify_password


def test_correct_and_wrong_password_with_random_salts():
    first, second = hash_password("fixture-password"),hash_password("fixture-password")
    assert first != second and "fixture-password" not in first
    assert first.startswith("scrypt$131072$8$1$")
    assert verify_password("fixture-password",first)
    assert not verify_password("wrong-password",first)
    assert verify_password("fixture-password",second)


@pytest.mark.parametrize("password", [None,"",42,"a"*1025])
def test_invalid_password_input_is_rejected(password):
    with pytest.raises(ValueError,match="password"):
        hash_password(password)


@pytest.mark.parametrize("stored", [None,"invalid","scrypt$1048576$8$1$"+"aa"*16+"$"+"ab"*32,
                                   "scrypt$131072$8$1$zzzz$abcd"])
def test_corrupt_or_unbounded_hash_parameters_are_rejected(stored):
    with pytest.raises(ValueError,match="stored password hash"):
        verify_password("fixture-password",stored)


def test_unicode_password_is_preserved():
    assert verify_password("모의 비밀번호",hash_password("모의 비밀번호"))
