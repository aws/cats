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

"""``_drop_run`` takes a superseded attempt out of the evidence: its entries, by identity, and the JUnit properties it put on the item.

The pytester tests in test_pytest_plugin_subtests.py drive it through pytest-rerunfailures; these
pin the two removal paths (the run's entries at the tail of ``entries``, popped; one of them
elsewhere, filtered) and the bookkeeping around them, which a pytester run cannot arrange.
"""

from types import SimpleNamespace
from typing import cast

import pytest

import cats.pytest_plugin
from cats.pytest_plugin import _drop_run, _ItemRun, _Recorded
from cats.reporting import ReportEntry


def make_entry(nodeid: str) -> ReportEntry:
    return {
        "result": "passed",
        "accounts_in_test": [],
        "test_name": nodeid.split("::", 1)[1],
        "nodeid": nodeid,
        "test_docstring": None,
        "standards": [],
        "standard_metadata": {},
        "custom_markers": {},
        "additional_metadata": {},
        "xfail": False,
        "error_message": None,
        "reason": None,
        "duration_s": 0.1,
        "recorded_at": "2026-09-24T10:53:17+00:00",
        "subtest": None,
    }


def make_item(user_properties: list[tuple[str, object]]) -> pytest.Item:
    """The two attributes ``_drop_run`` reads off the item: a list it cuts back, and nothing else."""
    return cast(pytest.Item, SimpleNamespace(user_properties=user_properties, nodeid="tests/test_a.py::test_b"))


def test_entries_at_the_tail_are_popped_and_the_rest_untouched() -> None:
    # arrange
    other = make_entry("tests/test_a.py::test_a")
    first = make_entry("tests/test_a.py::test_b")
    block = make_entry("tests/test_a.py::test_b [x]")
    cats.pytest_plugin.entries.extend([other, first, block])
    cats.pytest_plugin._runs["tests/test_a.py::test_b"] = _ItemRun(make_item([]), 0, [first, block])

    # act
    _drop_run("tests/test_a.py::test_b")

    # assert
    expected = [other]
    assert expected == cats.pytest_plugin.entries


def test_an_equal_entry_of_another_run_is_kept_removal_is_by_identity() -> None:
    """Two attempts can record equal entries; only the superseded attempt's own objects go."""
    # arrange
    earlier = make_entry("tests/test_a.py::test_b")
    this_run = make_entry("tests/test_a.py::test_b")
    cats.pytest_plugin.entries.extend([earlier, this_run])
    cats.pytest_plugin._runs["tests/test_a.py::test_b"] = _ItemRun(make_item([]), 0, [this_run])

    # act
    _drop_run("tests/test_a.py::test_b")

    # assert
    assert [earlier] == cats.pytest_plugin.entries
    assert cats.pytest_plugin.entries[0] is earlier


def test_an_entry_not_at_the_tail_is_filtered_out_of_the_whole_list() -> None:
    """The slow path: something else appended after the run's entry; the run's entries still go and nothing else does."""
    # arrange
    this_run = make_entry("tests/test_a.py::test_b")
    later = make_entry("tests/test_a.py::test_c")
    cats.pytest_plugin.entries.extend([this_run, later])
    cats.pytest_plugin._runs["tests/test_a.py::test_b"] = _ItemRun(make_item([]), 0, [this_run])

    # act
    _drop_run("tests/test_a.py::test_b")

    # assert
    expected = [later]
    assert expected == cats.pytest_plugin.entries


def test_the_runs_junit_properties_are_cut_back_and_earlier_ones_kept() -> None:
    """``item.user_properties`` is the one list for every attempt of the item, so only this run's additions go."""
    # arrange
    user_properties: list[tuple[str, object]] = [("before", "kept"), ("cats:standard", "SOC2-CC6.1"), ("cats:description", "Doc.")]
    cats.pytest_plugin._runs["tests/test_a.py::test_b"] = _ItemRun(make_item(user_properties), 1, [])

    # act
    _drop_run("tests/test_a.py::test_b")

    # assert
    expected = [("before", "kept")]
    assert expected == user_properties


def test_the_index_and_the_hand_off_forget_a_dropped_entry() -> None:
    # arrange
    this_run = make_entry("tests/test_a.py::test_b")
    cats.pytest_plugin.entries.append(this_run)
    cats.pytest_plugin._entries_by_nodeid["tests/test_a.py::test_b"] = this_run
    item = make_item([])
    cats.pytest_plugin._runs["tests/test_a.py::test_b"] = _ItemRun(item, 0, [this_run])
    cats.pytest_plugin._last_recorded = _Recorded(cast(pytest.Function, item), this_run, None, 0, "call")

    # act
    _drop_run("tests/test_a.py::test_b")

    # assert
    expected: tuple[dict[str, ReportEntry], _Recorded | None, list[ReportEntry]] = ({}, None, [])
    assert expected == (cats.pytest_plugin._entries_by_nodeid, cats.pytest_plugin._last_recorded, cats.pytest_plugin.entries)


def test_an_unknown_nodeid_is_a_no_op() -> None:
    """The xdist controller receives every rerun report and has recorded nothing."""
    # arrange
    kept = make_entry("tests/test_a.py::test_a")
    cats.pytest_plugin.entries.append(kept)

    # act
    _drop_run("tests/test_a.py::test_b")

    # assert
    assert [kept] == cats.pytest_plugin.entries
