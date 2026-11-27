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

"""``_failed_subtests_count_key``: the key pytest counts a test's failed blocks under, on the pytest at hand.

test_cats_counts_a_failed_block_under_the_key_pytest_itself_uses (test_pytest_plugin_subtests.py)
pins the key against pytest's own writer on whichever pytest is installed; these pin the three
shapes the function can meet, which one installed pytest cannot show together.
"""

from types import SimpleNamespace
from typing import cast

import pytest
from pytest_mock import MockerFixture

import cats.pytest_plugin
from cats.pytest_plugin import _failed_subtests_count_key

NODEID = "tests/test_a.py::test_b"


def make_item(**attributes: object) -> pytest.Item:
    """An item with a ``nodeid`` and whatever else the shape under test has."""
    return cast(pytest.Item, SimpleNamespace(nodeid=NODEID, **attributes))


def test_before_structured_ids_the_key_is_the_nodeid_text(mocker: MockerFixture) -> None:
    # arrange
    mocker.patch.object(cats.pytest_plugin, "_STRUCTURED_NODE_ID", False)
    item = make_item(id=object())  # an unrelated ``id`` another plugin gave the node

    # act
    key = _failed_subtests_count_key(item)

    # assert
    assert key == NODEID


def test_with_structured_ids_the_key_is_the_items_id(mocker: MockerFixture) -> None:
    # arrange
    mocker.patch.object(cats.pytest_plugin, "_STRUCTURED_NODE_ID", True)
    structured_id = object()
    item = make_item(id=structured_id)

    # act
    key = _failed_subtests_count_key(item)

    # assert
    assert structured_id is key


def test_structured_ids_without_an_id_on_the_node_degrade_to_the_nodeid_text(mocker: MockerFixture) -> None:
    """A pytest with ``_pytest.nodeid`` but no ``Node.id``: the nodeid, not an AttributeError inside the block's exit."""
    # arrange
    mocker.patch.object(cats.pytest_plugin, "_STRUCTURED_NODE_ID", True)
    item = make_item()

    # act
    key = _failed_subtests_count_key(item)

    # assert
    assert key == NODEID
