from __future__ import annotations

from pathlib import Path

import pytest

from campus_auth import config as config_mod
from campus_auth.config import Config, load


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把默认查找路径和工作目录都挪走，避免吃到本机真实配置。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(config_mod.ENV_PASSWORD, raising=False)
    monkeypatch.delenv(config_mod.ENV_CONFIG, raising=False)
    return tmp_path


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "campus-auth.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults(isolated: Path) -> None:
    config = load()
    assert config.operator == "none"
    assert config.retries == 2
    assert config.verify_tls is False


def test_file_is_read(isolated: Path) -> None:
    path = write(
        isolated, 'adapter = "huuc"\naccount = "123"\npassword = "pw"\noperator = "cmcc"\n'
    )
    config = load(path)
    assert config.adapter == "huuc"
    assert config.account == "123"
    assert config.operator == "cmcc"


def test_aliases_and_types(isolated: Path) -> None:
    path = write(
        isolated, 'school = "huuc"\nuser = "42"\nweak = "dx"\ntimeout = "9.5"\nretries = "4"\n'
    )
    config = load(path)
    assert (config.adapter, config.account, config.operator) == ("huuc", "42", "dx")
    assert config.timeout == 9.5
    assert config.retries == 4


def test_auth_section(isolated: Path) -> None:
    path = write(isolated, '[auth]\nadapter = "huuc"\naccount = "1"\n')
    assert load(path).account == "1"


def test_env_password_beats_file(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(isolated, 'adapter = "huuc"\naccount = "1"\npassword = "file"\n')
    monkeypatch.setenv(config_mod.ENV_PASSWORD, "env")
    assert load(path).password == "env"


def test_overrides_beat_env(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config_mod.ENV_PASSWORD, "env")
    assert load(None, {"password": "cli"}).password == "cli"


def test_none_overrides_ignored(isolated: Path) -> None:
    config = load(None, {"account": "keep", "operator": None})
    assert config.account == "keep"
    assert config.operator == "none"


def test_unknown_keys_ignored(isolated: Path) -> None:
    path = write(isolated, 'nonsense = "x"\nadapter = "huuc"\n')
    assert load(path).adapter == "huuc"


def test_bad_toml(isolated: Path) -> None:
    path = write(isolated, "adapter = [unclosed\n")
    with pytest.raises(config_mod.ConfigError):
        load(path)


def test_missing_explicit_file(isolated: Path) -> None:
    with pytest.raises(config_mod.ConfigError):
        load(isolated / "nope.toml")


@pytest.mark.parametrize("field", ["adapter", "account", "password"])
def test_validate_requires(field: str) -> None:
    config = Config(adapter="huuc", account="1", password="pw")
    setattr(config, field, "")
    with pytest.raises(config_mod.ConfigError):
        config.validate()


def test_validate_password_optional() -> None:
    Config(adapter="huuc", account="1").validate(need_password=False)


def test_validate_rejects_unknown_operator() -> None:
    with pytest.raises(config_mod.ConfigError, match="不认识运营商"):
        Config(adapter="generic", account="1", password="pw", operator="cmcc").validate()


def test_password_not_in_repr() -> None:
    assert "hunter2" not in repr(Config(adapter="huuc", account="1", password="hunter2"))


def test_password_falls_back_to_keyring(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import credentials

    path = write(isolated, 'adapter = "huuc"\naccount = "123"\n')
    monkeypatch.setattr(credentials, "get", lambda adapter, account: f"{adapter}:{account} 的密码")
    assert load(path).password == "huuc:123 的密码"


def test_config_password_beats_keyring(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import credentials

    path = write(isolated, 'adapter = "huuc"\naccount = "123"\npassword = "从文件"\n')
    monkeypatch.setattr(credentials, "get", lambda *_a: "从钥匙串")
    assert load(path).password == "从文件"


def test_env_password_beats_keyring(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_auth import credentials

    path = write(isolated, 'adapter = "huuc"\naccount = "123"\n')
    monkeypatch.setattr(credentials, "get", lambda *_a: "从钥匙串")
    monkeypatch.setenv(config_mod.ENV_PASSWORD, "从环境")
    assert load(path).password == "从环境"


def test_keyring_skipped_when_file_has_no_account(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from campus_auth import credentials

    called: list[tuple[str, str]] = []
    monkeypatch.setattr(credentials, "get", lambda a, acc: called.append((a, acc)) or "")
    load(write(isolated, 'adapter = "huuc"\n'))
    assert called == [("huuc", "")]


def test_keyring_uses_the_account_from_overrides(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`login -a 学号` 的学号必须参与钥匙串键，否则永远查空。"""
    from campus_auth import credentials

    called: list[tuple[str, str]] = []
    monkeypatch.setattr(
        credentials, "get", lambda adapter, account: called.append((adapter, account)) or "从钥匙串"
    )
    config = load(write(isolated, 'adapter = "huuc"\n'), {"account": "0814"})
    assert config.password == "从钥匙串"
    assert called == [("huuc", "0814")]


def test_override_account_selects_its_own_password(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配置里是 A、命令行给 B 时，不能拿 A 的密码去登 B。"""
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "get", lambda _adapter, account: f"{account} 的密码")
    path = write(isolated, 'adapter = "huuc"\naccount = "A"\n')
    assert load(path, {"account": "B"}).password == "B 的密码"


def test_env_still_beats_keyring_with_override(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from campus_auth import credentials

    monkeypatch.setattr(credentials, "get", lambda *_a: "从钥匙串")
    monkeypatch.setenv(config_mod.ENV_PASSWORD, "从环境")
    assert load(write(isolated, 'adapter = "huuc"\n'), {"account": "0814"}).password == "从环境"
