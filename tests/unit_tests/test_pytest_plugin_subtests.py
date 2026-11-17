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

"""A test that uses pytest's ``subtests`` fixture is recorded as pytest reports it: one entry per report.

Each ``subtests.test()`` block is an entry of its own, under the test's nodeid followed by
pytest's description of the block, with its own result and a ``subtest`` field naming the test.
The test's own entry follows pytest's rule: a body that passed while a block failed is ``failed``
with ``contains N failed subtests``; a body that failed or skipped keeps its own outcome.

Regression: each block's report used to be recorded as the test's own entry, so a test with
subtests had several entries under one nodeid and said ``passed`` when a block had failed.
"""

import json
import xml.etree.ElementTree as ET
from typing import Any

import pytest
import yaml

from tests.utils import make_config

# pytest-rerunfailures is a dev dependency for the rerun tests below and would otherwise load into
# every pytester run here; its makereport wrapper breaks a block run inside a fixture (its bug, not ours).
PLUGINS = ("-p", "no:randomly", "-p", "no:rerunfailures")
# The real plugin, one rerun: what its logging order does to the evidence is the thing under test.
RERUNS = ("-p", "no:randomly", "--reruns", "1")


@pytest.fixture
def cats_config_content() -> str:
    """Minimal cats.yaml config as string."""
    return yaml.dump(make_config(accounts={"testaccount": "234567890123"}))


def write_project(pytester: pytest.Pytester, cats_config_content: str, test_source: str) -> None:
    """Write cats.yaml, a conftest pointing CATS_CONFIG at it, and the test file."""
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(cats_config_content)
    pytester.makeconftest(f'''
import os
os.environ["CATS_CONFIG"] = "{config_path}"
''')
    pytester.makepyfile(test_source)


def read_report(pytester: pytest.Pytester) -> list[dict[str, Any]]:
    """The recorded entries without ``duration_s`` and ``recorded_at``, which vary run to run."""
    entries: list[dict[str, Any]] = json.loads((pytester.path / "report.json").read_text())["tests"]
    for entry in entries:
        del entry["duration_s"]
        del entry["recorded_at"]
    return entries


def read_counts(pytester: pytest.Pytester) -> dict[str, int]:
    counts: dict[str, int] = json.loads((pytester.path / "report.json").read_text())["run"]["counts"]
    return counts


def make_entry(
    nodeid: str,
    result: str,
    error_message: str | None = None,
    reason: str | None = None,
    subtest: dict[str, Any] | None = None,
    test_name: str | None = None,
) -> dict[str, Any]:
    """The entry a test named ``test_buckets`` with no markers or accounts records; ``test_name`` defaults from the nodeid."""
    return {
        "result": result,
        "accounts_in_test": [],
        "test_name": test_name if test_name is not None else nodeid.split("::", 1)[1],
        "nodeid": nodeid,
        "test_docstring": None,
        "standards": [],
        "standard_metadata": {},
        "custom_markers": {},
        "additional_metadata": {},
        "xfail": False,
        "error_message": error_message,
        "reason": reason,
        "subtest": subtest,
    }


def subtest_of(nodeid: str, msg: str | None, **context: str) -> dict[str, Any]:
    return {"of": nodeid, "msg": msg, "context": context}


def test_each_subtest_is_its_own_entry_and_the_body_is_rewritten(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest prints SUBFAILED, SUBPASSED and ``FAILED test_buckets - contains 1 failed subtest``; the report says the same."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test(msg="bucket-a"):
        assert False, "bucket-a public"
    with subtests.test(msg="bucket-b"):
        assert True
""",
    )
    parent = "test_each_subtest_is_its_own_entry_and_the_body_is_rewritten.py::test_buckets"
    expected = [
        make_entry(parent, "failed", "contains 1 failed subtest"),
        make_entry(f"{parent} [bucket-a]", "failed", "AssertionError: bucket-a public\nassert False", subtest=subtest_of(parent, "bucket-a")),
        make_entry(f"{parent} [bucket-b]", "passed", subtest=subtest_of(parent, "bucket-b")),
    ]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.assert_outcomes(failed=2, passed=0)
    result.stdout.fnmatch_lines(["*test_buckets*", "contains 1 failed subtest"])  # pytest's own words for the test, which the entry copies
    assert expected == read_report(pytester)


def test_counts_match_pytests_summary(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest's verbose summary says ``2 failed, 1 skipped, 1 xfailed, 1 subtests passed``: a failed block and its parent are both failures."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert False
    with subtests.test(msg="b"):
        assert True
    with subtests.test(msg="c"):
        pytest.skip("not in region")
    with subtests.test(msg="d"):
        pytest.xfail("known")
""",
    )
    expected = {"total": 5, "passed": 1, "failed": 2, "error": 0, "skipped": 1, "xfailed": 1, "xpassed": 0, "not_run": 0}

    # act
    result = pytester.runpytest_subprocess(*PLUGINS, "-v")

    # assert
    result.stdout.re_match_lines([r".*2 failed, 1 skipped, 1 xfailed, 1 subtests passed.*"])
    assert expected == read_counts(pytester)


def test_skipped_and_xfailed_subtests_carry_their_reason(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """``pytest.skip()`` and ``pytest.xfail()`` inside a block are the block's own outcome and reason."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

def test_buckets(subtests):
    with subtests.test(msg="c"):
        pytest.skip("not in region")
    with subtests.test(msg="d"):
        pytest.xfail("known")
""",
    )
    parent = "test_skipped_and_xfailed_subtests_carry_their_reason.py::test_buckets"
    expected_c = make_entry(f"{parent} [c]", "skipped", reason="not in region", subtest=subtest_of(parent, "c"))
    expected_d = make_entry(f"{parent} [d]", "xfailed", reason="known", subtest=subtest_of(parent, "d"))
    expected_d["xfail"] = True
    expected = [make_entry(parent, "passed"), expected_c, expected_d]

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert expected == read_report(pytester)


def test_plural_message_for_several_failed_subtests(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest's wording is ``contains 2 failed subtests``."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    for name in ("a", "b"):
        with subtests.test(msg=name):
            assert False
""",
    )

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert read_report(pytester)[0]["error_message"] == "contains 2 failed subtests"


def test_body_that_fails_keeps_its_own_message(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest rewrites only a passed body; a failed one reports its own failure."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert False, "a public"
    assert False, "body failed"
""",
    )

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    parent = read_report(pytester)[0]
    assert (parent["result"], parent["error_message"]) == ("failed", "AssertionError: body failed\nassert False")


def test_body_that_skips_after_a_failed_subtest_stays_skipped(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest leaves a skipped body skipped; the failure is the block's own entry."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert False, "a public"
    pytest.skip("rest not applicable")
""",
    )
    parent = "test_body_that_skips_after_a_failed_subtest_stays_skipped.py::test_buckets"
    expected = [
        make_entry(parent, "skipped", reason="rest not applicable"),
        make_entry(f"{parent} [a]", "failed", "AssertionError: a public\nassert False", subtest=subtest_of(parent, "a")),
    ]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.assert_outcomes(failed=1, skipped=1)
    assert expected == read_report(pytester)


def test_kwargs_are_the_description_and_the_context(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """The nodeid and ``context`` both carry pytest's own rendering of each keyword argument."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test(msg="bucket-a", region="us-east-1", days=365, public=False, owner=None, tags={"k": ["v", 1]}):
        assert True
""",
    )
    parent = "test_kwargs_are_the_description_and_the_context.py::test_buckets"
    description = "[bucket-a] (region='us-east-1', days=365, public=False, owner=None, tags={'k': ['v', 1]})"
    expected = [
        make_entry(parent, "passed"),
        make_entry(
            f"{parent} {description}",
            "passed",
            subtest=subtest_of(parent, "bucket-a", region="'us-east-1'", days="365", public="False", owner="None", tags="{'k': ['v', 1]}"),
        ),
    ]

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert expected == read_report(pytester)


def test_kwargs_are_kept_as_pytest_cut_them(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest cuts a rendering past 240 characters to ``...`` in the middle; ``context`` holds that text."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test(text="x" * 300):
        assert True
""",
    )
    expected = {"text": "'" + "x" * 117 + "..." + "x" * 118 + "'"}

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert expected == read_report(pytester)[1]["subtest"]["context"]


def test_subtest_without_msg_or_kwargs_is_described_as_pytest_does(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest shows ``(<subtest>)`` for a bare block."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test():
        assert True
""",
    )
    parent = "test_subtest_without_msg_or_kwargs_is_described_as_pytest_does.py::test_buckets"
    expected = [make_entry(parent, "passed"), make_entry(f"{parent} (<subtest>)", "passed", subtest=subtest_of(parent, None))]

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert expected == read_report(pytester)


def test_repeated_description_fails_the_second_block_and_names_the_fix(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """The description is the block's identity (Security Hub Ids and OSCAL uuids derive from the nodeid), so a repeat is an error.

    pytest prints the same line twice and is content; CATS fails the second block with the fix
    named, fails the run, and gives that entry `` #2`` so the report never holds two entries under
    one nodeid. The entry is still a block's: ``subtest`` names the test, so ``select(.subtest ==
    null)`` and ``cats/subtest_of`` see it as one. The test fails as it does for any failed block,
    with pytest's own wording: pytest had read the block's report before CATS failed it, so CATS
    adds the block to pytest's count itself. The first block, and a block with a distinct
    description, are recorded as usual.
    """
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    for _ in range(2):
        with subtests.test(msg="same"):
            assert True
    with subtests.test(msg="other"):
        assert True
""",
    )
    parent = "test_repeated_description_fails_the_second_block_and_names_the_fix.py::test_buckets"
    error_message = (
        "CATS reporting error (test itself may have passed, but this fails the test): "
        + f"duplicate subtest description '[same]' in {parent}: the description is the block's identity in the evidence, "
        + "so give each block a unique msg or keyword arguments."
    )
    expected = [
        make_entry(parent, "failed", "contains 1 failed subtest"),
        make_entry(f"{parent} [other]", "passed", subtest=subtest_of(parent, "other")),
        make_entry(f"{parent} [same]", "passed", subtest=subtest_of(parent, "same")),
        make_entry(f"{parent} [same] #2", "failed", error_message, subtest=subtest_of(parent, "same")),
    ]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.stdout.fnmatch_lines(["*CATS reporting error*duplicate subtest description*same*", "*_ test_buckets _*", "contains 1 failed subtest"])
    result.assert_outcomes(failed=2)  # the block and the test; passed blocks are pytest's own "subtests passed" category
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert expected == read_report(pytester)


def test_a_test_without_blocks_takes_the_path_it_always_did(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """``pytest_report_teststatus`` is asked once per plain test, by the terminal reporter; CATS asks it only for a test that ran a block.

    Pinned because the hook is ``firstresult`` and other plugins implement it: a second call per
    test would run their implementations twice for every test in every existing suite.
    """
    # arrange
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(cats_config_content)
    pytester.makeconftest(f'''
import os
os.environ["CATS_CONFIG"] = "{config_path}"

import pytest

calls = {{}}

@pytest.hookimpl(tryfirst=True)  # firstresult hook: pytest's own implementation answers, so count before it
def pytest_report_teststatus(report, config):
    if report.when == "call" and not isinstance(report, pytest.SubtestReport):
        calls[report.nodeid] = calls.get(report.nodeid, 0) + 1
    return None

def pytest_sessionfinish(session):
    (session.config.rootpath / "teststatus_calls.txt").write_text(repr(sorted(calls.items())))
''')
    pytester.makepyfile(
        """
def test_plain():
    assert True

def test_with_block(subtests):
    with subtests.test(msg="a"):
        assert True
"""
    )
    module = "test_a_test_without_blocks_takes_the_path_it_always_did.py"
    # pytest asks the hook once per report, from the terminal reporter; CATS adds one call for the test that ran a block.
    expected = [(f"{module}::test_plain", 1), (f"{module}::test_with_block", 2)]

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert repr(expected) == (pytester.path / "teststatus_calls.txt").read_text()


def test_subtests_inherit_the_tests_markers_accounts_and_docstring(pytester: pytest.Pytester) -> None:
    """Markers are item-level: a block's entry carries the test's standard, account and docstring, and its own result."""
    # arrange
    config = make_config(accounts={"testaccount": "234567890123"}, reporting={"custom_markers": ["team"]})
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(yaml.dump(config))
    # The account fixture reads the deployed stack; this run has no AWS, so the constructor is
    # reduced to the three attributes the reporter reads.
    pytester.makeconftest(f'''
import os
from unittest.mock import patch

os.environ["CATS_CONFIG"] = "{config_path}"

from cats.config import Settings
from cats.resources.account_under_test import AccountUnderTest

def fake_init(self, name):
    self.name = name
    self._account_config = Settings().accounts_under_test[name]
    self.account_id = self._account_config.account_id

patch.object(AccountUnderTest, "__init__", fake_init).start()
''')
    pytester.makepyfile(
        """
import pytest
from cats import cats

@cats(standard_name="SOC2-CC6.1", control_ids=["cc-6.1"])
@pytest.mark.team("payments")
def test_buckets(testaccount_account, subtests, cats_report):
    '''Every bucket is private.'''
    cats_report.add_report_metadata({"scanned": 1})
    with subtests.test(msg="bucket-a"):
        assert True
"""
    )
    parent = "test_subtests_inherit_the_tests_markers_accounts_and_docstring.py::test_buckets"
    expected_inherited = {
        "accounts_in_test": [{"account_name": "testaccount", "account_id": "234567890123", "tags": {}}],
        "test_docstring": "Every bucket is private.",
        "standards": ["SOC2-CC6.1"],
        "standard_metadata": {"SOC2-CC6.1": {"control_ids": ["cc-6.1"], "control_group": None}},
        "custom_markers": {"team": ["payments"]},
        "additional_metadata": {"scanned": 1},
    }
    expected = [
        {**make_entry(parent, "passed"), **expected_inherited},
        {**make_entry(f"{parent} [bucket-a]", "passed", subtest=subtest_of(parent, "bucket-a")), **expected_inherited},
    ]

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert expected == read_report(pytester)


def test_subtests_run_by_a_fixture_are_entries_and_a_teardown_failure_leaves_the_parent(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A block run after the body (fixture teardown) fails the run in pytest but not the test's own report; the report agrees."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def fx(subtests):
    with subtests.test(msg="before"):
        assert True
    yield
    with subtests.test(msg="after"):
        assert False, "after failed"

def test_buckets(fx, subtests):
    assert True
""",
    )
    parent = "test_subtests_run_by_a_fixture_are_entries_and_a_teardown_failure_leaves_the_parent.py::test_buckets"
    expected = [  # report.json is sorted by nodeid, so [after] precedes [before] whatever order they ran in
        make_entry(parent, "passed"),
        make_entry(f"{parent} [after]", "failed", "AssertionError: after failed\nassert False", subtest=subtest_of(parent, "after")),
        make_entry(f"{parent} [before]", "passed", subtest=subtest_of(parent, "before")),
    ]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.assert_outcomes(passed=1, failed=1)
    assert expected == read_report(pytester)


def test_teardown_error_still_upgrades_the_tests_own_entry(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A fixture that raises in teardown turns the test's own entry to error; the block's entry is untouched."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.fixture
def fx():
    yield
    raise RuntimeError("teardown exploded")

def test_buckets(fx, subtests):
    with subtests.test(msg="a"):
        assert True
""",
    )
    parent = "test_teardown_error_still_upgrades_the_tests_own_entry.py::test_buckets"
    expected = [
        make_entry(parent, "error", "RuntimeError: teardown exploded"),
        make_entry(f"{parent} [a]", "passed", subtest=subtest_of(parent, "a")),
    ]

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert expected == read_report(pytester)


def test_a_test_without_subtests_records_subtest_null(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """Every entry has the same columns; an ordinary test's ``subtest`` is null."""
    # arrange
    write_project(pytester, cats_config_content, "def test_plain(): assert True")
    expected = [make_entry("test_a_test_without_subtests_records_subtest_null.py::test_plain", "passed")]

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert expected == read_report(pytester)


def test_junit_is_pytests_one_testcase_with_cats_properties_once(pytester: pytest.Pytester) -> None:
    """pytest writes one testcase per test, a child per failed or skipped block and the test's own failure; CATS's properties go on it once."""
    # arrange
    config = make_config(accounts={"testaccount": "234567890123"}, reporting={"report_formats": ["cats_json", "junit"]})
    write_project(
        pytester,
        yaml.dump(config),
        """
import pytest
from cats import cats

@cats(standard_name="SOC2-CC6.1")
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert False, "a public"
    with subtests.test(msg="b"):
        assert True
    with subtests.test(msg="c"):
        pytest.skip("not in region")
""",
    )
    expected = {
        "testcases": 1,
        "children": [("failure", "AssertionError: a public\nassert False"), ("skipped", "not in region"), ("failure", "contains 1 failed subtest")],
        "cats:standard": ["SOC2-CC6.1"],
    }

    # act
    pytester.runpytest_subprocess(*PLUGINS)

    # assert
    testcases = ET.parse(pytester.path / "junit.xml").getroot().findall("./testsuite/testcase")  # noqa: S314 - XML written by this test's own pytest run
    actual = {
        "testcases": len(testcases),
        "children": [(child.tag, child.get("message")) for child in testcases[0] if child.tag != "properties"],
        "cats:standard": [prop.get("value") for prop in testcases[0].findall("./properties/property[@name='cats:standard']")],
    }
    assert expected == actual


def test_keep_duplicates_records_each_run_on_its_own(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """Two runs of one item share a nodeid; each gets its own entries, with pytest's wording, which counts by nodeid across both."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert False
""",
    )
    parent = "test_keep_duplicates_records_each_run_on_its_own.py::test_buckets"
    expected = [
        make_entry(parent, "failed", "contains 1 failed subtest"),
        make_entry(parent, "failed", "contains 2 failed subtests"),
    ] + [make_entry(f"{parent} [a]", "failed", "assert False", subtest=subtest_of(parent, "a"))] * 2

    # act
    result = pytester.runpytest_subprocess(*PLUGINS, "--keep-duplicates", f"{parent.split('::')[0]}", f"{parent.split('::')[0]}")

    # assert
    result.stdout.fnmatch_lines(["contains 1 failed subtest", "*", "contains 2 failed subtests"])
    assert expected == read_report(pytester)


def test_unittest_subtest_is_recorded_the_same_way(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """``TestCase.subTest`` blocks are entries the same way; pytest leaves a unittest test itself PASSED, and so does the report."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import unittest

class TestBuckets(unittest.TestCase):
    def test_buckets(self):
        with self.subTest(msg="a", region="us-east-1"):
            self.assertTrue(False)
""",
    )
    parent = "test_unittest_subtest_is_recorded_the_same_way.py::TestBuckets::test_buckets"

    # act
    result = pytester.runpytest_subprocess(*PLUGINS, "-rA")

    # assert
    report = read_report(pytester)
    assert [entry["nodeid"] for entry in report] == [parent, f"{parent} [a] (region='us-east-1')"]
    # Trailing ``*``: pytest appends `` - <message>`` to the SUBFAILED line when it does not truncate to the terminal width (CI=1).
    result.stdout.fnmatch_lines(["PASSED *TestBuckets::test_buckets", "SUBFAILED*TestBuckets::test_buckets*"])
    assert [entry["result"] for entry in report] == ["passed", "failed"]
    assert report[1]["subtest"] == {"of": parent, "msg": "a", "context": {"region": "'us-east-1'"}}


def test_xdist_workers_record_subtests_and_the_controller_records_nothing_twice(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """Workers ship subtest entries like any other; the controller, which receives every report too, must not add its own."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test(msg="a", n=1):
        assert False, "a public"
    with subtests.test(msg="b"):
        assert True

def test_other(subtests):
    with subtests.test(msg="c"):
        assert True
""",
    )
    module = "test_xdist_workers_record_subtests_and_the_controller_records_nothing_twice.py"
    expected = [
        make_entry(f"{module}::test_buckets", "failed", "contains 1 failed subtest"),
        make_entry(
            f"{module}::test_buckets [a] (n=1)",
            "failed",
            "AssertionError: a public\nassert False",
            subtest=subtest_of(f"{module}::test_buckets", "a", n="1"),
        ),
        make_entry(f"{module}::test_buckets [b]", "passed", subtest=subtest_of(f"{module}::test_buckets", "b")),
        make_entry(f"{module}::test_other", "passed"),
        make_entry(f"{module}::test_other [c]", "passed", subtest=subtest_of(f"{module}::test_other", "c")),
    ]

    # act
    pytester.runpytest_subprocess("-n", "2", *PLUGINS)

    # assert
    assert expected == read_report(pytester)


@pytest.mark.parametrize("workers", [(), ("-n", "1")], ids=["serial", "xdist"])
def test_reporting_error_on_a_subtest_fails_the_test_not_silently(
    pytester: pytest.Pytester, cats_config_content: str, workers: tuple[str, ...]
) -> None:
    """An exception while recording a block fails that report in pytest's summary, the run's exit status, the evidence, and its test.

    Regression: the report was marked failed in ``pytest_runtest_logreport``, after pytest's
    ``Session`` had counted it and after pytest had read it for the test's verdict, so the
    summary said failed while the exit status was 0 and both entries stayed ``passed``. CATS
    now does both counts itself; under xdist the controller's ``Session`` counts the worker's
    report as it arrived, failed, and the outcome must be the same.
    """
    # arrange
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(cats_config_content)
    pytester.makeconftest(f'''
import os
os.environ["CATS_CONFIG"] = "{config_path}"

from unittest.mock import patch
patch("cats.pytest_plugin._subtest_description", side_effect=RuntimeError("Simulated CATS error")).start()
''')
    pytester.makepyfile(
        """
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert True
"""
    )
    parent = "test_reporting_error_on_a_subtest_fails_the_test_not_silently.py::test_buckets"
    error_message = (
        "CATS reporting error (test itself may have passed, but this fails the test): "
        + f"a subtest of {parent} could not be described: RuntimeError('Simulated CATS error'); msg must be a string."
    )
    # The description could not be made, so the block gets the one description CATS supplies: never a second entry under the test's nodeid.
    expected = [
        make_entry(parent, "failed", "contains 1 failed subtest"),
        make_entry(f"{parent} [<undescribed subtest>]", "failed", error_message, subtest=subtest_of(parent, None)),
    ]

    # act
    result = pytester.runpytest_subprocess(*workers, *PLUGINS)

    # assert
    result.stdout.fnmatch_lines(["*CATS reporting error*Simulated CATS error*"])
    result.assert_outcomes(failed=2)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert expected == read_report(pytester)


def test_a_msg_whose_text_cannot_be_made_fails_the_block_under_its_own_nodeid(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A ``msg`` whose ``__str__`` raises cannot be described: the block gets ``[<undescribed subtest>]`` and fails, under its own nodeid.

    pytest cannot print it either: its terminal reporter raises inside the ``with``, which fails
    the test with that error. The block's entry is the one description CATS supplies rather than
    copies from pytest; a second such block in the same test would be a duplicate of it.
    """
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
class Unprintable:
    def __str__(self):
        raise ValueError("no text for this")

def test_buckets(subtests):
    with subtests.test(msg=Unprintable()):
        assert True
""",
    )
    parent = "test_a_msg_whose_text_cannot_be_made_fails_the_block_under_its_own_nodeid.py::test_buckets"
    error_message = (
        "CATS reporting error (test itself may have passed, but this fails the test): "
        + f"a subtest of {parent} could not be described: ValueError('no text for this'); msg must be a string."
    )
    expected = [
        make_entry(parent, "failed", "ValueError: no text for this"),
        make_entry(f"{parent} [<undescribed subtest>]", "failed", error_message, subtest=subtest_of(parent, None)),
    ]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.stdout.fnmatch_lines(["*CATS reporting failed*could not be described*no text for this*"])
    result.assert_outcomes(failed=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert expected == read_report(pytester)


def test_the_description_is_the_text_of_pytests_own_status_line(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """``_subtest_description`` re-renders what pytest prints; this pins the two to each other rather than to literal strings.

    pytest's ``-rA`` summary prints ``SUBFAILED<description> <nodeid> - <message>`` for every
    block; the block's entry nodeid is ``<nodeid> <description>``, so the description CATS
    composed must be the text between the label and the nodeid, for each shape: msg only,
    kwargs only, both, neither, and values pytest renders with ``repr``.
    """
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test(msg="bucket-a"):
        assert False
    with subtests.test(region="us-east-1", days=365):
        assert False
    with subtests.test(msg="bucket-b", tags={"env": "prod"}, versions=None):
        assert False
    with subtests.test():
        assert False
""",
    )
    module = "test_the_description_is_the_text_of_pytests_own_status_line.py"
    parent = f"{module}::test_buckets"

    # act
    result = pytester.runpytest_subprocess(*PLUGINS, "-rA")
    printed = sorted(
        line.removeprefix("SUBFAILED").split(" - ", 1)[0].removesuffix(f" {parent}").strip()
        for line in result.stdout.lines
        if line.startswith("SUBFAILED")
    )
    # pytest prints ``SUBFAILED<description> <nodeid>``; the entry nodeid is ``<nodeid> <description>``.
    recorded = sorted(entry["nodeid"].removeprefix(f"{parent} ") for entry in read_report(pytester) if entry["subtest"] is not None)

    # assert
    expected = sorted(["[bucket-a]", "(region='us-east-1', days=365)", "[bucket-b] (tags={'env': 'prod'}, versions=None)", "(<subtest>)"])
    assert (expected, expected) == (printed, recorded)


def test_non_string_msg_fails_that_block_and_names_it(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A ``msg`` that is not a string fails the block with the culprit named; the evidence file is still written whole.

    An int would survive json.dump, so the check is on the type, not on serializability: the docs
    say ``msg`` is a string or ``None``, kept verbatim. The failed entry is still a block's, with
    the value's text as its ``msg``.
    """
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
from pathlib import Path

def test_buckets(subtests):
    with subtests.test(msg=Path("bucket-a")):
        assert True
    with subtests.test(msg=7):
        assert True
""",
    )
    parent = "test_non_string_msg_fails_that_block_and_names_it.py::test_buckets"
    prefix = "CATS reporting error (test itself may have passed, but this fails the test): "
    path_message = (
        prefix + f"subtest msg PosixPath('bucket-a') in {parent} has type PosixPath: msg is kept verbatim in the evidence, so it must be a string."
    )
    int_message = prefix + f"subtest msg 7 in {parent} has type int: msg is kept verbatim in the evidence, so it must be a string."
    expected = [
        make_entry(parent, "failed", "contains 2 failed subtests"),
        make_entry(f"{parent} [7]", "failed", int_message, subtest=subtest_of(parent, "7")),
        make_entry(f"{parent} [bucket-a]", "failed", path_message, subtest=subtest_of(parent, "bucket-a")),
    ]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.stdout.fnmatch_lines(
        ["*CATS reporting error*subtest msg PosixPath('bucket-a')*has type PosixPath*", "*CATS reporting error*subtest msg 7*has type int*"]
    )
    result.assert_outcomes(failed=3)  # two blocks and their test
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert expected == read_report(pytester)


def test_a_block_that_failed_on_its_own_keeps_its_failure_when_recording_it_also_fails(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A duplicate block that also failed its assertion: the assertion comes first, the reporting error after it, in pytest's output and the entry."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test(msg="same"):
        assert True
    with subtests.test(msg="same"):
        assert False, "bucket public"
""",
    )
    parent = "test_a_block_that_failed_on_its_own_keeps_its_failure_when_recording_it_also_fails.py::test_buckets"
    error_message = (
        "AssertionError: bucket public\nassert False\n"
        + "CATS reporting error (test itself may have passed, but this fails the test): "
        + f"duplicate subtest description '[same]' in {parent}: the description is the block's identity in the evidence, "
        + "so give each block a unique msg or keyword arguments."
    )
    expected = [
        make_entry(parent, "failed", "contains 1 failed subtest"),
        make_entry(f"{parent} [same]", "passed", subtest=subtest_of(parent, "same")),
        make_entry(f"{parent} [same] #2", "failed", error_message, subtest=subtest_of(parent, "same")),
    ]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.stdout.fnmatch_lines(["*AssertionError: bucket public*", "*CATS reporting error*duplicate subtest description*"])
    result.assert_outcomes(failed=2, passed=0)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert expected == read_report(pytester)


def test_a_rerun_of_the_item_counts_descriptions_afresh(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """Running one item twice, as pytest-rerunfailures does, is two runs: the second run's blocks are not duplicates of the first's.

    The description count is reset when a run of the item starts. Without that, the second
    run's ``[a]`` would fail as a duplicate of the first's. The protocol is driven as
    pytest-rerunfailures drives it: ``runtestprotocol(log=False)`` makes the run's reports and
    they are logged afterwards (see test_reports_logged_after_teardown_still_give_the_test_pytests_verdict).
    """
    # arrange
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(cats_config_content)
    pytester.makeconftest(f'''
import os
os.environ["CATS_CONFIG"] = "{config_path}"

from _pytest.runner import runtestprotocol

def pytest_runtest_protocol(item, nextitem):
    for _ in range(2):
        item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
        for report in runtestprotocol(item, nextitem=nextitem, log=False):
            item.ihook.pytest_runtest_logreport(report=report)
        item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
''')
    pytester.makepyfile(
        """
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert True
"""
    )
    parent = "test_a_rerun_of_the_item_counts_descriptions_afresh.py::test_buckets"
    expected = [make_entry(parent, "passed")] * 2 + [make_entry(f"{parent} [a]", "passed", subtest=subtest_of(parent, "a"))] * 2

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.assert_outcomes(passed=2)
    assert result.ret == pytest.ExitCode.OK
    assert expected == read_report(pytester)


def test_reports_logged_after_teardown_still_give_the_test_pytests_verdict(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A run whose reports are logged in a batch after teardown, as pytest-rerunfailures logs them, records the same verdict as a plain run.

    Regression: the entry recorded at the call report was handed to ``pytest_runtest_logreport``
    on nodeid alone, so the setup report, logged first, took it and the call report found
    nothing; and the description count was reset at the teardown report, before any report was
    logged, so the test was never asked for pytest's verdict. The test read ``passed`` while
    pytest printed FAILED, under any ``--reruns`` value, 0 included.
    """
    # arrange
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(cats_config_content)
    pytester.makeconftest(f'''
import os
os.environ["CATS_CONFIG"] = "{config_path}"

from _pytest.runner import runtestprotocol

def pytest_runtest_protocol(item, nextitem):
    item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    for report in runtestprotocol(item, nextitem=nextitem, log=False):
        item.ihook.pytest_runtest_logreport(report=report)
    item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
''')
    pytester.makepyfile(
        """
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert False, "bucket public"
"""
    )
    parent = "test_reports_logged_after_teardown_still_give_the_test_pytests_verdict.py::test_buckets"
    expected = [
        make_entry(parent, "failed", "contains 1 failed subtest"),
        make_entry(f"{parent} [a]", "failed", "AssertionError: bucket public\nassert False", subtest=subtest_of(parent, "a")),
    ]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.assert_outcomes(failed=2)
    assert expected == read_report(pytester)


def test_a_block_failed_by_a_reporting_error_stops_a_run_under_maxfail(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """``-x`` stops after a block CATS failed, as it does after a block that failed on its own.

    pytest's ``Session`` counts failures before this plugin fails the report, so the plugin adds
    the count itself; the same count is what makes the exit status TESTS_FAILED without a
    session flag of CATS's own. Regression: the run continued past the failure, and the exit
    status was rescued only by a flag read at session end.
    """
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    for _ in range(2):
        with subtests.test(msg="same"):
            assert True

def test_never_reached():
    assert True
""",
    )
    module = "test_a_block_failed_by_a_reporting_error_stops_a_run_under_maxfail.py"
    expected_nodeids = [f"{module}::test_buckets", f"{module}::test_buckets [same]", f"{module}::test_buckets [same] #2"]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS, "-x")

    # assert
    result.stdout.fnmatch_lines(["*stopping after 1 failures*"])
    result.assert_outcomes(failed=2)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert expected_nodeids == [entry["nodeid"] for entry in read_report(pytester)]


@pytest.mark.parametrize("workers", [(), ("-n", "1")], ids=["serial", "xdist"])
def test_a_rerun_leaves_the_last_attempts_entries_only(pytester: pytest.Pytester, cats_config_content: str, workers: tuple[str, ...]) -> None:
    """A block that fails once and passes on the rerun: the evidence is the last attempt, one entry per nodeid, as pytest's summary counts it.

    pytest-rerunfailures logs the superseded attempt's reports with the outcome ``rerun`` and
    takes the attempt out of pytest's tallies; CATS takes its entries out of the evidence. The
    plugin logs the rerun report on the worker, where the entries are, so xdist is the same.

    Regression: both attempts were recorded, so report.json held two entries under each nodeid
    (two Security Hub findings with one Id, last write wins), and the first attempt's test entry
    read ``passed``: its call report arrived as ``rerun``, which is not ``failed``, so the
    body's verdict was never rewritten.
    """
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
ATTEMPTS = {"a": 0}

def test_buckets(subtests):
    with subtests.test(msg="a"):
        ATTEMPTS["a"] += 1
        assert ATTEMPTS["a"] > 1, "first attempt"
    with subtests.test(msg="b"):
        assert True
""",
    )
    parent = "test_a_rerun_leaves_the_last_attempts_entries_only.py::test_buckets"
    expected = [
        make_entry(parent, "passed"),
        make_entry(f"{parent} [a]", "passed", subtest=subtest_of(parent, "a")),
        make_entry(f"{parent} [b]", "passed", subtest=subtest_of(parent, "b")),
    ]
    expected_counts = {"total": 3, "passed": 3, "failed": 0, "error": 0, "skipped": 0, "xfailed": 0, "xpassed": 0, "not_run": 0}

    # act
    result = pytester.runpytest_subprocess(*workers, *RERUNS)

    # assert
    result.stdout.fnmatch_lines(["*1 passed, 1 rerun*"])  # passed blocks are printed only at a higher subtests verbosity
    assert result.ret == pytest.ExitCode.OK
    assert (expected, expected_counts) == (read_report(pytester), read_counts(pytester))


def test_a_rerun_after_a_setup_or_teardown_failure_leaves_the_last_attempts_entry_only(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """The entry a setup error or a teardown failure recorded goes with its attempt, whichever report carried the ``rerun`` outcome.

    A failed setup records an ``error`` entry at the setup report; a failed teardown upgrades
    the call entry after the call report was logged as passed. Both attempts are superseded and
    both entries go, so a plain test (no blocks) also has one entry after a rerun.
    """
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

ATTEMPTS = {"setup": 0, "teardown": 0}

@pytest.fixture
def flaky_setup():
    ATTEMPTS["setup"] += 1
    assert ATTEMPTS["setup"] > 1, "setup first attempt"

@pytest.fixture
def flaky_teardown():
    yield
    ATTEMPTS["teardown"] += 1
    assert ATTEMPTS["teardown"] > 1, "teardown first attempt"

def test_setup(flaky_setup):
    assert True

def test_teardown(flaky_teardown):
    assert True
""",
    )
    module = "test_a_rerun_after_a_setup_or_teardown_failure_leaves_the_last_attempts_entry_only.py"
    expected = [make_entry(f"{module}::test_setup", "passed"), make_entry(f"{module}::test_teardown", "passed")]

    # act
    result = pytester.runpytest_subprocess(*RERUNS)

    # assert
    # pytest's own tally keeps the superseded attempt's passed call report (logged before its teardown failed), so it
    # says 3 passed for 2 tests; the evidence does not, and counts 2.
    result.stdout.fnmatch_lines(["*3 passed, 2 rerun*"])
    assert result.ret == pytest.ExitCode.OK
    assert (expected, 2) == (read_report(pytester), read_counts(pytester)["passed"])


def test_a_test_that_fails_every_attempt_is_recorded_once(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """When the reruns are used up, the last attempt is the one logged as failed, and it is the only one in the evidence."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert False, "every time"
""",
    )
    parent = "test_a_test_that_fails_every_attempt_is_recorded_once.py::test_buckets"
    expected = [
        make_entry(parent, "failed", "contains 1 failed subtest"),
        make_entry(f"{parent} [a]", "failed", "AssertionError: every time\nassert False", subtest=subtest_of(parent, "a")),
    ]

    # act
    result = pytester.runpytest_subprocess(*RERUNS)

    # assert
    result.stdout.fnmatch_lines(["*2 failed, 1 rerun*"])
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert expected == read_report(pytester)


def test_a_rerun_leaves_the_last_attempts_junit_properties_only(pytester: pytest.Pytester) -> None:
    """The ``cats:`` properties of a superseded attempt go with it.

    pytest-rerunfailures runs the same item, whose ``user_properties`` list junitxml reads whole.
    pytest writes one testcase per attempt (the superseded one carries the first attempt's
    ``<failure>``); the last testcase is the test's record, and it carries each property once.
    Regression: it carried every property twice, once per attempt.
    """
    # arrange
    config = make_config(accounts={"testaccount": "234567890123"}, reporting={"report_formats": ["cats_json", "junit"]})
    write_project(
        pytester,
        yaml.dump(config),
        """
from cats import cats

ATTEMPTS = {"a": 0}

@cats(standard_name="SOC2-CC6.1")
def test_buckets(subtests):
    '''Every bucket is private.'''
    with subtests.test(msg="a"):
        ATTEMPTS["a"] += 1
        assert ATTEMPTS["a"] > 1, "first attempt"
""",
    )
    expected = {
        "testcases": 2,
        "last_children": [],
        "last_properties": [("cats:standard", "SOC2-CC6.1"), ("cats:description", "Every bucket is private.")],
    }

    # act
    result = pytester.runpytest_subprocess(*RERUNS)

    # assert
    assert result.ret == pytest.ExitCode.OK
    testcases = ET.parse(pytester.path / "junit.xml").getroot().findall("./testsuite/testcase")  # noqa: S314 - XML written by this test's own pytest run
    actual = {
        "testcases": len(testcases),
        "last_children": [child.tag for child in testcases[-1] if child.tag != "properties"],
        "last_properties": [(prop.get("name"), prop.get("value")) for prop in testcases[-1].findall("./properties/property")],
    }
    assert expected == actual


def test_without_pytests_failed_block_count_a_reporting_error_still_fails_the_block_and_the_run(
    pytester: pytest.Pytester, cats_config_content: str
) -> None:
    """The count is a private pytest name, looked up rather than imported: a pytest that moved it degrades one path and loads the plugin still.

    Without it, CATS cannot add a block it failed to the test's count, so the test keeps the
    result pytest gave it; the block and the run fail as before.
    """
    # arrange
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(cats_config_content)
    pytester.makeconftest(f'''
import os
os.environ["CATS_CONFIG"] = "{config_path}"

import cats.pytest_plugin
cats.pytest_plugin._FAILED_SUBTESTS_KEY = None
''')
    pytester.makepyfile(
        """
def test_buckets(subtests):
    for _ in range(2):
        with subtests.test(msg="same"):
            assert True
"""
    )
    parent = "test_without_pytests_failed_block_count_a_reporting_error_still_fails_the_block_and_the_run.py::test_buckets"
    expected_results = [(parent, "passed"), (f"{parent} [same]", "passed"), (f"{parent} [same] #2", "failed")]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.assert_outcomes(failed=1, passed=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert expected_results == [(entry["nodeid"], entry["result"]) for entry in read_report(pytester)]


def test_cats_counts_a_failed_block_under_the_key_pytest_itself_uses(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """The failed-block count CATS adds to is read back by pytest only under pytest's own key, whatever this pytest keys it by.

    A block that failed on its own is counted by pytest's writer; the key it was counted under
    is the one CATS must use for a block it fails. Regression: pytest 9.2 keys the count by
    the structured ``id`` where 9.1 keyed it by the ``nodeid`` text, and a count under the
    text was one 9.2 never read, so a block CATS failed left its test passed, silently,
    within the pin a fresh install resolves.
    """
    # arrange
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(cats_config_content)
    pytester.makeconftest(f'''
import json
import os
os.environ["CATS_CONFIG"] = "{config_path}"

import pytest

import cats.pytest_plugin as plugin


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item):
    counted = item.config.stash[plugin._FAILED_SUBTESTS_KEY]
    found = {{
        "keys_pytest_counted": len(counted),
        "count_under_cats_key": counted.get(plugin._failed_subtests_count_key(item)),
    }}
    (item.config.rootpath / "count.json").write_text(json.dumps(found))
''')
    pytester.makepyfile(
        """
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert False
"""
    )
    expected = {"keys_pytest_counted": 1, "count_under_cats_key": 1}

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert expected == json.loads((pytester.path / "count.json").read_text())


def test_a_block_whose_evidence_cannot_be_built_is_still_a_blocks_entry(pytester: pytest.Pytester) -> None:
    """A marker value json cannot represent fails the entry of every report of the test: each block's and the test's own.

    The entry recorded in place of each is the fallback (no markers, accounts or metadata) and
    is handed on as any entry is, so the block's is renamed to the block's nodeid and the
    test's keeps its own. The block's failure is counted by pytest itself here, since the report
    is failed before pytest reads it; the test's own report fails on its own recording error,
    so it keeps that message rather than ``contains 1 failed subtest``.
    """
    # arrange
    config = make_config(accounts={"testaccount": "234567890123"}, reporting={"custom_markers": ["team"]})
    write_project(
        pytester,
        yaml.dump(config),
        """
import pytest

@pytest.mark.team(object())
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert True
""",
    )
    parent = "test_a_block_whose_evidence_cannot_be_built_is_still_a_blocks_entry.py::test_buckets"
    error_message = (
        "CATS reporting error (test itself may have passed, but this fails the test): "
        + f"evidence entry for '{parent}' is not JSON-serializable: Object of type object is not JSON serializable. "
        + "Marker values, control_ids, and metadata must be JSON types (str/int/float/bool/None/list/dict)."
    )
    expected = [
        make_entry(parent, "failed", error_message),
        make_entry(f"{parent} [a]", "failed", error_message, subtest=subtest_of(parent, "a")),
    ]

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.assert_outcomes(failed=2)
    assert expected == read_report(pytester)


def test_xfail_marked_test_with_a_failing_block_is_recorded_as_pytest_reports_it(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest prints ``SUBXFAIL[a]`` for the block and ``XPASS`` for the test: the block's failure is expected, the body passed."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.xfail(reason="known")
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert False
""",
    )
    parent = "test_xfail_marked_test_with_a_failing_block_is_recorded_as_pytest_reports_it.py::test_buckets"
    expected_parent = make_entry(parent, "xpassed")
    expected_parent["xfail"] = True
    expected_block = make_entry(f"{parent} [a]", "xfailed", reason="known", subtest=subtest_of(parent, "a"))
    expected_block["xfail"] = True

    # act
    result = pytester.runpytest_subprocess(*PLUGINS, "-v")

    # assert
    result.stdout.fnmatch_lines(["*SUBXFAIL*[a]*", "*test_buckets XPASS*"])
    assert [expected_parent, expected_block] == read_report(pytester)


def test_strict_xfail_marked_test_with_a_passing_block_fails_as_pytest_reports_it(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest prints ``SUBFAILED[a]`` and ``FAILED`` with ``[XPASS(strict)]``: both entries are failed with that message."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.xfail(reason="known", strict=True)
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert True
""",
    )
    parent = "test_strict_xfail_marked_test_with_a_passing_block_fails_as_pytest_reports_it.py::test_buckets"
    expected_parent = make_entry(parent, "failed", "[XPASS(strict)] known")
    expected_parent["xfail"] = True
    expected_block = make_entry(f"{parent} [a]", "failed", "[XPASS(strict)] known", subtest=subtest_of(parent, "a"))
    expected_block["xfail"] = True

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.assert_outcomes(failed=2)
    assert [expected_parent, expected_block] == read_report(pytester)


def test_reporting_error_in_setup_is_an_error_not_a_skip(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A reporting error while recording a setup skip marks that report failed: pytest reports an error where it would have reported a skip."""
    # arrange
    config_path = pytester.path / "cats.yaml"
    config_path.write_text(cats_config_content)
    pytester.makeconftest(f'''
import os
os.environ["CATS_CONFIG"] = "{config_path}"

from unittest.mock import patch
patch("cats.pytest_plugin.get_cats_reporter", side_effect=RuntimeError("Simulated CATS error")).start()
''')
    pytester.makepyfile(
        """
import pytest

@pytest.mark.skip(reason="not here")
def test_buckets():
    assert True
"""
    )

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.stdout.fnmatch_lines(["*CATS reporting error*Simulated CATS error*"])
    result.assert_outcomes(errors=1)


def test_xfail_marked_test_with_a_passing_block_is_xpassed_twice(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """pytest prints XPASS for the block and XPASS for the test under a non-strict marker; both entries say so."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.xfail(reason="known")
def test_buckets(subtests):
    with subtests.test(msg="a"):
        assert True
""",
    )
    parent = "test_xfail_marked_test_with_a_passing_block_is_xpassed_twice.py::test_buckets"
    expected_parent = make_entry(parent, "xpassed")
    expected_parent["xfail"] = True
    expected_block = make_entry(f"{parent} [a]", "xpassed", subtest=subtest_of(parent, "a"))
    expected_block["xfail"] = True

    # act
    result = pytester.runpytest_subprocess(*PLUGINS, "-v")

    # assert
    result.stdout.fnmatch_lines(["*test_buckets XPASS*", "*test_buckets XPASS*"])
    assert [expected_parent, expected_block] == read_report(pytester)


def test_xfail_raises_mismatch_in_a_block_fails_as_pytest_reports_it(pytester: pytest.Pytester, cats_config_content: str) -> None:
    """A block raising something other than ``raises=`` is SUBFAILED, and the passed body is rewritten, as pytest does."""
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.xfail(reason="known", raises=KeyError)
def test_buckets(subtests):
    with subtests.test(msg="a"):
        raise ValueError("wrong type")
""",
    )
    parent = "test_xfail_raises_mismatch_in_a_block_fails_as_pytest_reports_it.py::test_buckets"
    expected_parent = make_entry(parent, "failed", "contains 1 failed subtest")
    expected_parent["xfail"] = True
    expected_block = make_entry(f"{parent} [a]", "failed", "ValueError: wrong type", subtest=subtest_of(parent, "a"))
    expected_block["xfail"] = True

    # act
    result = pytester.runpytest_subprocess(*PLUGINS)

    # assert
    result.assert_outcomes(failed=2)
    assert [expected_parent, expected_block] == read_report(pytester)


@pytest.mark.parametrize("workers", [(), ("-n", "1")], ids=["serial", "xdist"])
def test_an_expected_failure_block_that_fails_in_reporting_is_failed_not_xfailed(
    pytester: pytest.Pytester, cats_config_content: str, workers: tuple[str, ...]
) -> None:
    """A duplicate block under an xfail marker: pytest had it ``SUBXFAIL``; the reporting error makes it ``SUBFAILED`` and ``failed``.

    pytest's status label reads ``wasxfail`` off the report, so a report marked failed must lose
    it, or the summary would print an expected failure for a block whose entry is failed. Under
    xdist the deletion happens on the worker before the report is sent, so the controller's
    summary must show the same. The test, XPASS on its own, fails as it does for any failed
    block (pytest prints ``FAILED (known)``: the rewrite keeps the marker's reason).
    """
    # arrange
    write_project(
        pytester,
        cats_config_content,
        """
import pytest

@pytest.mark.xfail(reason="known")
def test_buckets(subtests):
    for _ in range(2):
        with subtests.test(msg="same"):
            assert False
""",
    )
    parent = "test_an_expected_failure_block_that_fails_in_reporting_is_failed_not_xfailed.py::test_buckets"
    error_message = (
        "CATS reporting error (test itself may have passed, but this fails the test): "
        + f"duplicate subtest description '[same]' in {parent}: the description is the block's identity in the evidence, "
        + "so give each block a unique msg or keyword arguments."
    )
    expected_parent = make_entry(parent, "failed", "contains 1 failed subtest")
    expected_parent["xfail"] = True
    expected_first = make_entry(f"{parent} [same]", "xfailed", reason="known", subtest=subtest_of(parent, "same"))
    expected_first["xfail"] = True
    expected_second = make_entry(f"{parent} [same] #2", "failed", error_message, subtest=subtest_of(parent, "same"))
    expected_second["xfail"] = True

    # act
    result = pytester.runpytest_subprocess(*workers, *PLUGINS, "-v")

    # assert
    result.stdout.fnmatch_lines(["*SUBXFAIL[[]same[]]*", "*SUBFAILED[[]same[]]*", "*CATS reporting error*duplicate subtest description*"])
    result.assert_outcomes(failed=2, xfailed=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert [expected_parent, expected_first, expected_second] == read_report(pytester)


@pytest.mark.parametrize("workers", [(), ("-n", "1")], ids=["serial", "xdist"])
def test_a_block_that_failed_on_its_own_and_in_reporting_keeps_pytests_structured_failure(
    pytester: pytest.Pytester, workers: tuple[str, ...]
) -> None:
    """The reporting error is a titled section after the block's own traceback, and the section survives the xdist round trip.

    junitxml's ``<failure message>`` for the block is still its own crash line (read off the
    structured longrepr; text in its place would make the whole traceback the message), the
    ``<failure>`` body ends with the reporting error, and the FAILURES section prints the error
    under its own separator. Under xdist the section is added on the worker and serialized with
    the report (``longrepr.sections``), so the controller prints and writes the same.
    """
    # arrange
    config = make_config(accounts={"testaccount": "234567890123"}, reporting={"report_formats": ["cats_json", "junit"]})
    write_project(
        pytester,
        yaml.dump(config),
        """
def test_buckets(subtests):
    for _ in range(2):
        with subtests.test(msg="same"):
            assert 1 == 3, "block failure"
""",
    )
    parent = "test_a_block_that_failed_on_its_own_and_in_reporting_keeps_pytests_structured_failure.py::test_buckets"
    reporting_error = (
        "CATS reporting error (test itself may have passed, but this fails the test): "
        + f"duplicate subtest description '[same]' in {parent}: the description is the block's identity in the evidence, "
        + "so give each block a unique msg or keyword arguments."
    )
    expected = [
        ("AssertionError: block failure\nassert 1 == 3", False),
        ("AssertionError: block failure\nassert 1 == 3", True),
        ("contains 2 failed subtests", False),
    ]

    # act
    result = pytester.runpytest_subprocess(*workers, *PLUGINS)

    # assert
    result.stdout.fnmatch_lines(["*- CATS reporting error -*", reporting_error])
    failures = ET.parse(pytester.path / "junit.xml").getroot().findall("./testsuite/testcase/failure")  # noqa: S314 - XML written by this test's own pytest run
    assert expected == [(failure.get("message"), (failure.text or "").endswith(reporting_error)) for failure in failures]
