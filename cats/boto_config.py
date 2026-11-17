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

"""The botocore client configuration every CATS session applies by default."""

from botocore.config import Config

BOTO_RETRY_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"})
"""Retry policy for every client CATS builds.

``adaptive`` retries throttling and 5xx responses and rate-limits the client to what the service
is accepting. Ten attempts outlast a burst from several runs sharing one Region's request limit
for a service such as SSM or Security Hub. Installed as the default client config by
:func:`cats.user_agent.attributed_botocore_session`; a caller's own ``config=`` merges over it per
top-level option, so a caller that sets ``retries`` replaces this policy as a unit.
"""
