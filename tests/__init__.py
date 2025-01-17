#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

import mock
from girder import constants, logger

# Mock the logging methods so that we don't actually write logs to disk,
# and so tests can potentially inspect calls to logging methods.
print(constants.TerminalColor.warning('Mocking girder log methods.'))
for method in ('info', 'error', 'exception'):
    setattr(logger, method, mock.MagicMock())
