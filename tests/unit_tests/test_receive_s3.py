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

"""Tests for NetworkHandler.receive_s3 and _receive_s3_by_id."""

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from pytest_mock import MockerFixture

from cats.constants import CatsNetworkResponse, CatsNetworkResult
from cats.exceptions import CatsInfrastructureError, CatsUsageError
from cats.resources.network_interact import NetworkHandler, register_udp_receipt_token
from tests.unit_tests.test_network_handler import make_handler
from tests.utils import make_ssm_response

CORRELATION_ID = "3f2a1b4c-5d6e-4f70-8192-a3b4c5d6e7f8"
BUCKET = "cats-responses-123456789012"
ACCOUNT_ID = "123456789012"
# A second placeholder account, so a test can tell the account under test apart from the parent account.
OTHER_ACCOUNT_ID = "222222222222"


def _not_found() -> ClientError:
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")


@pytest.fixture
def mock_s3() -> MagicMock:
    return MagicMock()


@pytest.fixture
def handler(cats_yaml: Path, mock_s3: MagicMock) -> NetworkHandler:
    return make_handler(cats_yaml, mock_s3, ["ec2"])


@pytest.fixture
def no_sleep(mocker: MockerFixture) -> MagicMock:
    mock: MagicMock = mocker.patch("cats.resources.network_interact.time.sleep")
    return mock


def _sent(
    correlation_id: str | None = CORRELATION_ID,
    response: CatsNetworkResponse = CatsNetworkResponse.SENT,
    reason: str | None = None,
    receipt_token_carried: bool = True,
) -> CatsNetworkResult:
    return CatsNetworkResult(response=response, reason=reason, correlation_id=correlation_id, _receipt_token_carried=receipt_token_carried)


# The exact CatsUsageError message receive_s3 raises for a SENT result with CORRELATION_ID that carried no receipt token.
UNTOKENED_REFUSAL = (
    f"receive_s3 needs a datagram that carried the receipt token; the one with correlation_id '{CORRELATION_ID}' went without one, "
    + "because no token was registered for the host you passed to udp_call. A CATS listener drops such a datagram, so False here would "
    + "not be evidence that the network dropped it. Address the listener by its ec2_dns_name, and make sure the receiving account was "
    + "constructed before udp_call ran (in pytest, the test requests that account's fixture): that is what registers the token. For a "
    + "target that is not a CATS listener, do not call receive_s3."
)


# =============================================================================
# receive_s3
# =============================================================================


def test_receipt_found_returns_true(handler: NetworkHandler, mock_s3: MagicMock) -> None:
    # arrange
    mock_s3.head_object.return_value = {}

    # act
    result = handler.receive_s3(_sent())

    # assert
    assert result is True
    mock_s3.head_object.assert_called_once_with(Bucket=BUCKET, Key=CORRELATION_ID, ExpectedBucketOwner=ACCOUNT_ID)


def test_receipt_not_found_within_timeout_returns_false(
    handler: NetworkHandler, mock_s3: MagicMock, no_sleep: MagicMock, mocker: MockerFixture
) -> None:
    # arrange - two polls fit before the deadline
    mock_s3.head_object.side_effect = _not_found()
    mocker.patch("cats.resources.network_interact.time.time", side_effect=[100.0, 100.0, 102.0, 104.0])

    # act
    result = handler.receive_s3(_sent(), timeout=4, interval=2)

    # assert
    assert result is False
    assert mock_s3.head_object.call_count == 2


def test_receipt_appears_on_a_later_poll_returns_true(handler: NetworkHandler, mock_s3: MagicMock, no_sleep: MagicMock) -> None:
    # arrange
    mock_s3.head_object.side_effect = [_not_found(), {}]

    # act
    result = handler.receive_s3(_sent(), timeout=10, interval=2)

    # assert
    assert result is True
    no_sleep.assert_called_once_with(2)


def test_non_404_client_error_is_an_infrastructure_error(handler: NetworkHandler, mock_s3: MagicMock) -> None:
    """A receipt that cannot be checked must not read as False, and callers must not need botocore's exception types."""
    # arrange
    mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "HeadObject")
    expected_message = (
        f"Cannot read receipt '{CORRELATION_ID}' from response bucket '{BUCKET}' of account 'test_account': AccessDenied. "
        + "The bucket is created by 'cats infra deploy' and read through the account's default test role; redeploy if the stack changed."
    )

    # act
    with pytest.raises(CatsInfrastructureError) as exc_info:
        handler.receive_s3(_sent())

    # assert
    assert str(exc_info.value) == expected_message


def test_result_without_correlation_id_raises_value_error(handler: NetworkHandler, mock_s3: MagicMock) -> None:
    # arrange - an HTTP/TCP result was passed
    tcp_result = CatsNetworkResult(response=CatsNetworkResponse.SUCCESS)
    expected_message = "receive_s3 needs the result of a udp_call; SUCCESS() carries no correlation_id"

    # act & assert
    with pytest.raises(CatsUsageError) as exc_info:
        handler.receive_s3(tcp_result)
    assert str(exc_info.value) == expected_message
    mock_s3.head_object.assert_not_called()


def test_non_sent_result_raises_value_error_with_repr(handler: NetworkHandler, mock_s3: MagicMock) -> None:
    # arrange - the datagram never left; a False here would false-pass an isolation test
    dns_failure = _sent(response=CatsNetworkResponse.DNS_FAILURE, reason="[Errno -2] Name or service not known")
    expected_message = (
        "receive_s3 needs a SENT result; the datagram never left the host: "
        + f"DNS_FAILURE('[Errno -2] Name or service not known', correlation_id='{CORRELATION_ID}')"
    )

    # act & assert
    with pytest.raises(CatsUsageError) as exc_info:
        handler.receive_s3(dns_failure)
    assert str(exc_info.value) == expected_message
    mock_s3.head_object.assert_not_called()


def test_untokened_datagram_result_raises_usage_error(handler: NetworkHandler, mock_s3: MagicMock) -> None:
    """A listener addressed by IP gets an untokened datagram and drops it; a False here would false-pass a denial test."""
    # arrange
    untokened = _sent(receipt_token_carried=False)

    # act & assert
    with pytest.raises(CatsUsageError) as exc_info:
        handler.receive_s3(untokened)
    assert str(exc_info.value) == UNTOKENED_REFUSAL
    mock_s3.head_object.assert_not_called()


def test_token_carrying_result_is_polled(handler: NetworkHandler, mock_s3: MagicMock) -> None:
    """The result udp_call returns for a listener addressed by ec2_dns_name: the token was carried and the bucket is polled."""
    # arrange
    mock_s3.head_object.return_value = {}

    # act
    result = handler.receive_s3(_sent(receipt_token_carried=True))

    # assert
    assert result is True
    mock_s3.head_object.assert_called_once_with(Bucket=BUCKET, Key=CORRELATION_ID, ExpectedBucketOwner=ACCOUNT_ID)


def test_hand_built_sent_result_is_polled(handler: NetworkHandler, mock_s3: MagicMock) -> None:
    """The external-sender form from docs/concepts/network-testing.md is taken to carry the token (the default) and is polled."""
    # arrange
    mock_s3.head_object.return_value = {}
    hand_built = CatsNetworkResult(response=CatsNetworkResponse.SENT, correlation_id=CORRELATION_ID)

    # act
    result = handler.receive_s3(hand_built)

    # assert
    assert result is True
    mock_s3.head_object.assert_called_once_with(Bucket=BUCKET, Key=CORRELATION_ID, ExpectedBucketOwner=ACCOUNT_ID)


# =============================================================================
# udp_call -> receive_s3, end to end: the result udp_call builds is the one receive_s3 judges
# =============================================================================


@pytest.fixture
def mock_ssm_and_s3() -> MagicMock:
    """One client mock serving as SSM for ec2_udp_call and as S3 for receive_s3 (make_handler hands out a single client)."""
    mock = MagicMock()
    mock.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
    mock.describe_instance_information.return_value = {"InstanceInformationList": []}
    mock.get_command_invocation.return_value = make_ssm_response("Success", "SENT")
    mock.head_object.return_value = {}
    return mock


@pytest.fixture
def end_to_end_handler(cats_yaml: Path, mock_ssm_and_s3: MagicMock, mocker: MockerFixture) -> NetworkHandler:
    mocker.patch("uuid.uuid4", return_value=uuid.UUID(CORRELATION_ID))
    return make_handler(cats_yaml, mock_ssm_and_s3, ["ec2"])


def test_udp_call_to_a_host_with_no_token_is_refused_by_receive_s3(end_to_end_handler: NetworkHandler, mock_ssm_and_s3: MagicMock) -> None:
    """The two halves agree: the flag udp_call clears is the one receive_s3 tests, and the bucket is never polled."""
    # arrange
    sent = end_to_end_handler.ec2_udp_call("10.0.1.5", 5000)

    # act
    with pytest.raises(CatsUsageError) as exc_info:
        end_to_end_handler.receive_s3(sent)

    # assert
    assert (str(exc_info.value), mock_ssm_and_s3.head_object.called) == (UNTOKENED_REFUSAL, False)


def test_udp_call_to_a_registered_listener_is_polled_by_receive_s3(end_to_end_handler: NetworkHandler, mock_ssm_and_s3: MagicMock) -> None:
    """Addressed by the registered ec2_dns_name, the datagram carries the token and receive_s3 polls for its correlation ID."""
    # arrange
    register_udp_receipt_token("ip-10-0-1-5.ec2.internal", "0123456789abcdef0123456789abcdef")
    sent = end_to_end_handler.ec2_udp_call("ip-10-0-1-5.ec2.internal", 5000)

    # act
    result = end_to_end_handler.receive_s3(sent)

    # assert
    assert result is True
    mock_ssm_and_s3.head_object.assert_called_once_with(Bucket=BUCKET, Key=CORRELATION_ID, ExpectedBucketOwner=ACCOUNT_ID)


# =============================================================================
# _receive_s3_by_id - the CLI and MCP path, which has only the raw ID
# =============================================================================


def test_by_id_polls_the_raw_correlation_id(handler: NetworkHandler, mock_s3: MagicMock) -> None:
    # arrange
    mock_s3.head_object.return_value = {}

    # act
    result = handler._receive_s3_by_id("abc-123")

    # assert
    assert result is True
    mock_s3.head_object.assert_called_once_with(Bucket=BUCKET, Key="abc-123", ExpectedBucketOwner=ACCOUNT_ID)


def test_head_object_asserts_the_account_under_test_as_bucket_owner(cats_yaml: Path, mock_s3: MagicMock) -> None:
    """The owner is the account under test, read from the host: not the parent account, and not derived from the bucket name.

    CloudFormation names the bucket `<stack>-catsresponsebucket-<random>`, so there is no account in the name
    to derive from; the host's account differs from the parent (123456789012) so the two cannot be confused.
    """
    # arrange
    bucket = "cats-test-infra-test-account-catsresponsebucket-1a2b3c4d5e6f"
    handler = make_handler(cats_yaml, mock_s3, ["ec2"], account_id=OTHER_ACCOUNT_ID, response_bucket_name=bucket)
    mock_s3.head_object.return_value = {}

    # act
    handler._receive_s3_by_id("abc-123")

    # assert
    mock_s3.head_object.assert_called_once_with(Bucket=bucket, Key="abc-123", ExpectedBucketOwner=OTHER_ACCOUNT_ID)


def test_receive_s3_delegates_to_by_id_with_timeout_and_interval(handler: NetworkHandler, mocker: MockerFixture) -> None:
    # arrange
    by_id = mocker.patch.object(handler, "_receive_s3_by_id", return_value=True)

    # act
    handler.receive_s3(_sent(), timeout=15.0, interval=3.0)

    # assert
    by_id.assert_called_once_with(CORRELATION_ID, 15.0, 3.0)


def test_receive_s3_defaults_are_ten_second_timeout_and_two_second_interval(handler: NetworkHandler, mocker: MockerFixture) -> None:
    # arrange
    by_id = mocker.patch.object(handler, "_receive_s3_by_id", return_value=True)

    # act
    handler.receive_s3(_sent())

    # assert
    by_id.assert_called_once_with(CORRELATION_ID, 10.0, 2.0)


def test_receive_s3_timeout_is_keyword_only(handler: NetworkHandler, mock_s3: MagicMock) -> None:
    # arrange
    expected_message = "NetworkHandler.receive_s3() takes 2 positional arguments but 3 were given"

    # act & assert
    with pytest.raises(TypeError) as exc_info:
        handler.receive_s3(_sent(), 15.0)  # type: ignore[misc]
    assert str(exc_info.value) == expected_message
    mock_s3.head_object.assert_not_called()
