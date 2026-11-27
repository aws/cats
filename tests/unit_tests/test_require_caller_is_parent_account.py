# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for require_caller_is_parent_account: deploy refuses test roles that would trust an account other than the caller's."""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from cats.cfn.session import require_caller_is_parent_account
from cats.exceptions import CatsConfigError
from tests.utils import write_config


@pytest.fixture
def mock_current_account(mocker: MockerFixture) -> MagicMock:
    """The deploying credentials belong to 111122223333."""
    return mocker.patch("cats.cfn.session.get_current_account_id", return_value="111122223333")


def test_parent_account_other_than_the_caller_raises_config_error(cats_yaml: Path, mock_current_account: MagicMock) -> None:
    # arrange
    write_config(cats_yaml, {"cats_deployment_settings": {"parent_account_id": "123456789012"}})
    expected_message = (
        "cats_deployment_settings.parent_account_id is 123456789012, but 'cats infra deploy' is running as account 111122223333 "
        + "(the account 'aws sts get-caller-identity' reports). "
        + "The test roles trust the parent account and the deploy assumes them from these credentials: "
        + "set parent_account_id to 111122223333, or deploy with credentials from account 123456789012."
    )

    # act & assert
    with pytest.raises(CatsConfigError, match=f"^{re.escape(expected_message)}$"):
        require_caller_is_parent_account()


def test_parent_account_equal_to_the_caller_passes_after_one_caller_lookup(cats_yaml: Path, mock_current_account: MagicMock) -> None:
    # arrange
    write_config(cats_yaml, {"cats_deployment_settings": {"parent_account_id": "111122223333"}})

    # act
    require_caller_is_parent_account()

    # assert
    assert mock_current_account.call_count == 1


def test_unset_parent_account_passes_without_a_caller_lookup(cats_yaml: Path, mock_current_account: MagicMock) -> None:
    """render_template refuses an unset parent_account_id with its own message; this check leaves that case to it."""
    # arrange
    write_config(cats_yaml, {})

    # act
    require_caller_is_parent_account()

    # assert
    assert mock_current_account.call_count == 0
