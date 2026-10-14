from unittest.mock import MagicMock

import pytest

from mealie.services.app_info_service import AppInfoService


@pytest.mark.parametrize("group_private", [True, False])
@pytest.mark.parametrize("household_private", [True, False])
def test_default_slugs_respect_privacy(
    monkeypatch: pytest.MonkeyPatch, group_private: bool, household_private: bool
) -> None:
    public_repos = MagicMock()
    group_repos = MagicMock()
    group = public_repos.groups.get_by_name.return_value
    group.slug = "default-group"
    group.preferences.private_group = group_private
    household = group_repos.households.get_by_name.return_value
    household.slug = "default-household"
    household.preferences.private_household = household_private
    get_repos = MagicMock(side_effect=[public_repos, group_repos])
    monkeypatch.setattr("mealie.services.app_info_service.get_repositories", get_repos)
    session = MagicMock()

    result = AppInfoService().get_info(session)

    assert result.default_group_slug == (None if group_private else "default-group")
    assert result.default_household_slug == (None if group_private or household_private else "default-household")
    if group_private:
        assert get_repos.call_count == 1
    else:
        get_repos.assert_called_with(session, group_id=group.id, household_id=None)


@pytest.mark.parametrize("default_users", [0, 1])
def test_startup_info_default_user(monkeypatch: pytest.MonkeyPatch, default_users: int) -> None:
    repos = MagicMock()
    repos.users.count_all.return_value = default_users
    monkeypatch.setattr("mealie.services.app_info_service.get_repositories", lambda *args, **kwargs: repos)
    service = AppInfoService()
    result = service.get_startup_info(MagicMock())
    assert result.is_first_login is bool(default_users)
    repos.users.count_all.assert_called_once_with("email", service.settings._DEFAULT_EMAIL)
