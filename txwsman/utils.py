#!/usr/bin/env python
import logging
import os
import re
import base64
import uuid
from twisted.python.log import err
from twisted.web.client import Agent
from twisted.internet import reactor
from twisted.internet.ssl import ClientContextFactory
from twisted.internet.ssl import CertificateOptions
from twisted.internet.protocol import Protocol
from collections import namedtuple
from twisted.internet import reactor, defer
from twisted.web.http_headers import Headers
from xml.etree import cElementTree as ET

_CONTENT_TYPE = {'Content-Type': ['application/soap+xml;charset=UTF-8']}
_REQUEST_TEMPLATE_NAMES = ('identify', 'enumerate')
_REQUEST_TEMPLATES = {}
_REQUEST_TEMPLATE_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'request')
_XML_WHITESPACE_PATTERN = re.compile(r'>\s+<')

log = logging.getLogger('zen.wsman.utils')
log.setLevel(level=logging.DEBUG)
ConnectionInfo = namedtuple( 'ConnectionInfo',
                      ['hostname', 'auth_type', 'username', 'password', 'scheme', 'port',
                       'connectiontype', 'keytab'])
_AGENT = None
_MAX_PERSISTENT_PER_HOST = 200
_CACHED_CONNECTION_TIMEOUT = 24000
_CONNECT_TIMEOUT = 500

class MyWebClientContextFactory(object):

    def __init__(self):
        self._options = CertificateOptions()

    def getContext(self, hostname, port):
        return self._options.getContext()


def _get_agent():
    global _AGENT
    if _AGENT is None:
        context_factory = MyWebClientContextFactory()
        try:
            # HTTPConnectionPool has been present since Twisted version 12.1
            from twisted.web.client import HTTPConnectionPool
            pool = HTTPConnectionPool(reactor, persistent=True)
            pool.maxPersistentPerHost = _MAX_PERSISTENT_PER_HOST
            pool.cachedConnectionTimeout = _CACHED_CONNECTION_TIMEOUT
            _AGENT = Agent(reactor, context_factory,
                           connectTimeout=_CONNECT_TIMEOUT, pool=pool)
        except ImportError:
            try:
                # connectTimeout first showed up in Twisted version 11.1
                _AGENT = Agent(
                    reactor, context_factory, connectTimeout=_CONNECT_TIMEOUT)
            except TypeError:
                _AGENT = Agent(reactor, context_factory)
    return _AGENT

def _get_basic_auth_header(conn_info):
    authstr = "{0}:{1}".format(conn_info.username, conn_info.password)
    return 'Basic {0}'.format(base64.encodestring(authstr).strip())

@defer.inlineCallbacks
def _get_url_and_headers(conn_info):
    url = "{c.scheme}://{c.hostname}:{c.port}/wsman".format(c=conn_info)
    headers = Headers(_CONTENT_TYPE)
    headers.addRawHeader('Connection', conn_info.connectiontype)
    if conn_info.auth_type == 'basic':
        headers.addRawHeader(
            'Authorization', _get_basic_auth_header(conn_info))
    elif conn_info.auth_type == 'kerberos':
        yield _authenticate_with_kerberos(conn_info, url)
    else:
        raise Exception('unknown auth type: {0}'.format(conn_info.auth_type))
    defer.returnValue((url, headers))

def _get_request_template(name):
    if name not in _REQUEST_TEMPLATE_NAMES:
        raise Exception('Invalid request template name: {0}'.format(name))
    if name not in _REQUEST_TEMPLATES:
        path = os.path.join(_REQUEST_TEMPLATE_DIR, '{0}.xml'.format(name))
        with open(path) as f:
            _REQUEST_TEMPLATES[name] = \
                _XML_WHITESPACE_PATTERN.sub('><', f.read()).strip()
    return _REQUEST_TEMPLATES[name]

class _StringProducer(object):
    """
    The length attribute must be a non-negative integer or the constant
    twisted.web.iweb.UNKNOWN_LENGTH. If the length is known, it will be used to
    specify the value for the Content-Length header in the request. If the
    length is unknown the attribute should be set to UNKNOWN_LENGTH. Since more
    servers support Content-Length, if a length can be provided it should be.
    """

    def __init__(self, body):
        self._body = body
        self.length = len(body)

    def startProducing(self, consumer):
        """
        This method is used to associate a consumer with the producer. It
        should return a Deferred which fires when all data has been produced.
        """
        consumer.write(self._body)
        return defer.succeed(None)

    def pauseProducing(self):
        pass

    def stopProducing(self):
        pass


class RequestSender(object):
    def __init__(self, conn_info):
        #verify_conn_info(conn_info)
        self._conn_info = conn_info
        self._url = None
        self._headers = None

    @defer.inlineCallbacks
    def _set_url_and_headers(self):
        self._url, self._headers = yield _get_url_and_headers(self._conn_info)

    @defer.inlineCallbacks
    def send_request(self, request_template_name, **kwargs):
        log.debug('sending request: {0} {1}'.format(
            request_template_name, kwargs))

        yield self._set_url_and_headers()
        request = _get_request_template(request_template_name).format(**kwargs)
        body_producer = _StringProducer(request)
        response = yield _get_agent().request('POST', self._url, self._headers, body_producer)
        log.debug('received response {0} {1}'.format(
            response.code, request_template_name))
        defer.returnValue(response)
    
def create_request_sender(conn_info):
    sender = RequestSender(conn_info)
    return sender
    #return EtreeRequestSender(sender)

class _StringProtocol(Protocol):

    def __init__(self):
        self.d = defer.Deferred()
        self._data = []

    def dataReceived(self, data):
        self._data.append(data)

    def connectionLost(self, reason):
        self.d.callback(''.join(self._data))

if __name__ == '__main__':
    logging.basicConfig()
    defer.setDebugging(True)

    def stop_reactor(*args, **kwargs):
        if reactor.running:
            reactor.stop()


    @defer.inlineCallbacks
    def main():
        hostname = 'z2'
        auth_type = 'basic'
        username = 'eedgar'
        password = 'zenoss'
        connectiontype = 'Keep-Alive'
        scheme = 'https'
        port = '5986'
        keytab = ''

        conn_info = ConnectionInfo(
                  hostname,
                  auth_type,
                  username,
                  password,
                  scheme,
                  port,
                  connectiontype,
                  keytab,)
        s=create_request_sender(conn_info)
        resp = yield s.send_request('enumerate',
                                    uuid=str(uuid.uuid4()),resource_uri='https://z2:5986/wsman')
        proto = _StringProtocol()
        resp.deliverBody(proto)
        xml_str = yield proto.d
        if log.isEnabledFor(logging.DEBUG):
            try:
                import xml.dom.minidom
                xml = xml.dom.minidom.parseString(xml_str)
                log.debug(xml.toprettyxml())
            except:
                log.debug('Could not prettify response XML: "{0}"'.format(xml_str))
        stop_reactor()


    reactor.callWhenRunning(main)
    reactor.run()

