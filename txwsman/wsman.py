##############################################################################
#
# Copyright (C) Zenoss, Inc. 2013, all rights reserved.
#
# This content is made available according to terms specified in the LICENSE
# file at the top-level directory of this package.
#
##############################################################################

"""
Use twisted web client to enumerate/pull WQL query.
"""

import sys
from twisted.internet import defer
from . import app
from strategies import BaseStrategy

if __name__ == '__main__':
    app.main(WsmanUtility(WsmanStrategy()))
