"""Simple TCP sockets.

Each Actor has a TCP IPv4 port/socket that will accept incoming
connections for messages.  Each connection from a remote Actor will
accept a single message per connection.  The connection is dropped and
re-established for multiple messages; this is less efficient but has
more fairness.

This transport can be used within a process, between processes, and
even between processes on separate systems.

"""


# n.b. The core of this is very similar to asyncore/asynchat.
# Unfortunately, those modules are deprecated in Python 3.4 in favor
# of asyncio, which is powerful... and complex.  Thespian aims to
# support Python 2.6 through 3.4 and beyond, and has more specific
# needs (undoubtably a subset of asyncio capabilities) that can be
# implemented more simply and directly here.  In addition, this module
# should be extensible to support SSL, which asynchat is not (maybe).

# For Thespian, there are two classes of sockets:
#   * the Actor's primary receive socket, and
#   * transient outgoing send sockets.
# All steps of both types of sockets are handled asynchronously, very
# similarly to the asyncore channel.
#
# For the receive socket, it will listen for and accept incoming
# connections, and then accept a single message on that connection,
# closing the connection on completion (or error).
#
# For the transmit socket, it will connect, send, and close with a
# TransmitIntent.

# ----------------------------------------------------------------------

# TCP Buffering issues
#
# TCP is unique in that there are unusual buffering considerations to
# account for.  Specifically, a sender can connect to a listener, send
# a message, and close the socket --- *WITHOUT the receiver even
# processing the accept!  As a result, the transmitter must take
# additional steps to ensure that the message that was sent has been
# delivered.
#
# There are two ways that this confirmation can be handled:
#
#  1) confirmation sent back in the original connection
#
#  2) messages confirmed by a separate confirmation message with a
#     unique message identifier for idempotency.
#
# Disadvantages of #1:
#   * More complicated exchange between sender and receiver
#   * There must be a header synchronization with a size indicator so
#     that the receiver knows when the full message has been received
#     and should be acknowledged.
#   * The socket must exist for a potentially much longer period and
#     retransmits must still be attempted on failure.
#
# Disadvantages of #2:
#   * Doubles connection establishment requirements.
#   * More complicated send queuing to ensure ordering of messages between
#     sender and recipient.  However, this really must exist for condition
#     #1 as well.
#
# Could also do a hybrid of both.  On send, start with header
# containing message ID (and size?) then wait a brief time after send
# for the ACK, then disconnect and wait for the separate ACK later.
#
# At this point, the connection establishment seems to be the
# overriding performance dominator, and the message header
# synchronization and size indication seem like good ideas anyhow to
# confirm that the entire message has been received by the recipient.
# This method is feasible because of the asynchronous handling of the
# transmit sequence (as opposed to a blocking transmit, which would
# consume the processing budget for highly active scenarios).

import logging
from thespian.system.utilis import (thesplog, fmap, partition)
from thespian.system.timing import timePeriodSeconds, ExpirationTimer
from thespian.actors import *
from thespian.system.transport import *
from thespian.system.transport.IPBase import (TCPv4ActorAddress)
from thespian.system.transport.streamBuffer import (toSendBuffer,
                                                    ReceiveBuffer,
                                                    ackMsg, ackPacket,
                                                    ackDataErrMsg,
                                                    isControlMessage)
from thespian.system.transport.asyncTransportBase import asyncTransportBase
from thespian.system.transport.wakeupTransportBase import wakeupTransportBase
from thespian.system.transport.errmgmt import *
from thespian.system.messages.multiproc import ChildMayHaveDied
from thespian.system.addressManager import ActorLocalAddress
import socket
import select
from datetime import timedelta
try:
    import cPickle as pickle
except Exception:
    import pickle
import errno
from contextlib import closing

DEFAULT_ADMIN_PORT = 1900


serializer = pickle
# json cannot be used because Messages are often structures, which
# cannot be converted to JSON.

# max # of listens to sign up for at a time
LISTEN_DEPTH = 100

# max time to hold open an incoming socket
MAX_INCOMING_SOCKET_PERIOD = timedelta(minutes=7)

MAX_CONSECUTIVE_READ_FAILURES = 20

# close idle sockets after this amount of time
MAX_IDLE_SOCKET_PERIOD = timedelta(minutes=20)

# if true, keep sockets open for multiple messages
REUSE_SOCKETS = True


class TCPEndpoint(TransportInit__Base):
    def __init__(self, *args): self.args = args

    @property
    def addrInst(self): return self.args[0]


def _safeSocketShutdown(sock):
    if sock:
        sock = getattr(sock, 'socket', sock)
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except socket.error as ex:
            if ex.errno != errno.ENOTCONN:
                thesplog('Error during shutdown of socket %s: %s', sock, ex)
        sock.close()


class TCPIncoming_Common(PauseWithBackoff):
    def __init__(self, rmtAddr, baseSock, rcvBuf=None):
        super(TCPIncoming_Common, self).__init__()
        self._openSock = baseSock
        # _rmtAddr may be None until a message is rcvd with
        # identification
        self._rmtAddr = rmtAddr
        self._rData = rcvBuf or ReceiveBuffer(serializer.loads)
        self._expires = ExpirationTimer(MAX_INCOMING_SOCKET_PERIOD)
        self.failCount = 0

    @property
    def socket(self):
        return self._openSock

    @property
    def fromAddress(self):
        return self._rmtAddr

    @fromAddress.setter
    def fromAddress(self, newAddr):
        self._rmtAddr = newAddr

    def delay(self):
        # n.b. include _pauseUntil from PauseWithBackoff
        return max(timedelta(seconds=0),
                   min(self._expires.remaining(),
                       getattr(self, '_pauseUntil', self._expires).remaining()))

    def addData(self, newData): self._rData.addMore(newData)

    def remainingSize(self): return self._rData.remainingAmount()

    def receivedAllData(self): return self._rData.isDone()

    @property
    def data(self): return self._rData.completed()

    def close(self):
        _safeSocketShutdown(self)
        self._openSock = None

    def __str__(self):
        return 'TCPInc(%s)<%s>' % (str(self._rmtAddr), str(self._rData))


class TCPIncoming(TCPIncoming_Common):
    def __del__(self):
        _safeSocketShutdown(s.socket)
        self._openSock = None


class TCPIncomingPersistent(TCPIncoming_Common):
    pass



class IdleSocket(object):
    def __init__(self, socket, addr):
        self.socket = socket
        self.rmtaddr = addr
        # n.b. the remote may have bound an outbound connect socket to
        # a different address, but rmtAddr represents the primary
        # address of an Actor/Admin: the one it listens on.
        # self.rmtAddr = rmtAddr
        self.validity = ExpirationTimer(MAX_IDLE_SOCKET_PERIOD)

    def expired(self):
        return self.validity.expired()

    def __str__(self):
        return 'Idle-socket %s->%s (%s)' % (str(self.socket),
                                            str(self.rmtaddr),
                                            str(self.validity))

    def shutdown(self, shtarg=socket.SHUT_RDWR):
        self.socket.shutdown(shtarg)

    def close(self):
        self.socket.close()


def opsKey(addr):
    return addr.addressDetails


# The definition of these two address types has moved to IPBase, but
# declare them here as well for backward compatibility with older
# running Thespian instances.
import thespian.system.transport.IPBase
class RoutedTCPv4ActorAddress(
        thespian.system.transport.IPBase.RoutedTCPv4ActorAddress):
    pass
class TXOnlyAdminTCPv4ActorAddress(
        thespian.system.transport.IPBase.TXOnlyAdminTCPv4ActorAddress):
    pass


class ExternalTransportCopy(object): pass



class TCPTransport(asyncTransportBase, wakeupTransportBase):
    "A transport using TCP IPv4 sockets for communications."

    def __init__(self, initType, *args):
        super(TCPTransport, self).__init__()

        if isinstance(initType, ExternalInterfaceTransportInit):
            # External process that is going to talk "in".  There is
            # no parent, and the child is the systemAdmin.
            capabilities, logDefs, concurrency_context = args
            adminRouting     = False
            self.txOnly      = False  # communications from outside-in are always local and therefore not restricted.
            convAddr = capabilities.get('Convention Address.IPv4', '')
            if convAddr and type(convAddr) == type( (1,2) ):
                externalAddr = convAddr
            elif type(convAddr) == type("") and ':' in convAddr:
                externalAddr = convAddr.split(':')
                externalAddr      = externalAddr[0], int(externalAddr[1])
            else:
                externalAddr = (convAddr, capabilities.get('Admin Port', DEFAULT_ADMIN_PORT))
            templateAddr     = ActorAddress(TCPv4ActorAddress(None, 0, external = externalAddr))
            self._adminAddr  = self.getAdminAddr(capabilities)
            self._parentAddr = None
            isAdmin = False
        elif isinstance(initType, TCPEndpoint):
            instanceNum, assignedAddr, self._parentAddr, self._adminAddr, adminRouting, self.txOnly = initType.args
            isAdmin = assignedAddr == self._adminAddr
            templateAddr = assignedAddr or \
                           ActorAddress(
                               TCPv4ActorAddress(None, 0,
                                                 external=(self._parentAddr or
                                                           self._adminAddr or
                                                           True)))
        elif isinstance(initType, ExternalTransportCopy):
            self._adminAddr, self.txOnly, adminRouting = args
            self._parentAddr = None
            isAdmin = False
            templateAddr = ActorAddress(
                TCPv4ActorAddress(None, 0, self._adminAddr))
        else:
            thesplog('TCPTransport init of type %s unsupported', type(initType), level=logging.ERROR)
            raise ActorSystemStartupFailure('Invalid TCPTransport init type (%s)'%type(initType))

        self.socket = socket.socket(*templateAddr.addressDetails.socketArgs)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(*templateAddr.addressDetails.bindArgs)
        self.socket.listen(LISTEN_DEPTH)
        # N.B.  myAddress is actually the address we will export for
        # others to talk to us, not the bind address.  The difference
        # is that we bind to '0.0.0.0' (inaddr_any), but that's not a
        # valid address for people to send stuff to us.  The
        # self.socket socket name is likely inaddr_any but has the
        # valid port, whereas the templateAddr has our actual public
        # address.
        if isAdmin and self.txOnly:
            # Must be the admin, and in txOnly mode
            self.myAddress = ActorAddress(TXOnlyAdminTCPv4ActorAddress(
                templateAddr.addressDetails.connectArgs[0][0],
                self.socket.getsockname()[1],
                external=True))
        elif adminRouting:
            self.myAddress = ActorAddress(RoutedTCPv4ActorAddress(
                templateAddr.addressDetails.connectArgs[0][0],
                self.socket.getsockname()[1],
                self._adminAddr,
                txOnly=self.txOnly,
                external=True))
        else:
            self.myAddress = ActorAddress(TCPv4ActorAddress(
                templateAddr.addressDetails.connectArgs[0][0],
                self.socket.getsockname()[1],
                external=True))
        self._transmitIntents = {}  # key = fd, value = tx intent
        self._waitingTransmits = []  # list of intents without sockets
        self._incomingSockets = {}  # key = fd, value = TCP Incoming
        self._incomingEnvelopes = []
        self._watches = []
        if REUSE_SOCKETS:
            # key = opsKey(remote listen address), value=IdleSocket
            self._openSockets = {}
        self._checkChildren = False
        self._shutdownSignalled = False

    def close(self):
        """Releases all resources and terminates functionality.  This is
           better done deterministically by explicitly calling this
           method (although __del__ will attempt to perform similar
           operations), but it has the unfortunate side-effect of
           making this object modal: after the close it can be
           referenced but not successfully used anymore, so it
           explicitly nullifies its contents.
        """
        if hasattr(self, '_transmitIntents'):
            for each in self._transmitIntents:
                self._transmitIntents[each].tx_done(SendStatus.Failed)
            delattr(self, '_transmitIntents')
        if hasattr(self, '_waitingTransmits'):
            for each in self._waitingTransmits:
                each.tx_done(SendStatus.Failed)
            delattr(self, '_waitingTransmits')
        if hasattr(self, '_incomingSockets'):
            for each in self._incomingSockets:
                self._incomingSockets[each].close()
            delattr(self, '_incomingSockets')
        if hasattr(self, 'socket'):
            self._safeSocketShutdown(getattr(self, 'socket', None))
            delattr(self, 'socket')

    def __del__(self):
        self.close()

    @staticmethod
    def _safeSocketShutdown(sock):
        # n.b. _safeSocketShutdown is a static method instead of a
        # global because if __del__ calls close, the
        # _safeSocketShutdown may already have been unbound.  However,
        # this still needs unusual protection to validate socket in
        # case socket was already unloaded.
        if sock and socket and isinstance(socket.error, Exception):
            sock = getattr(sock, 'socket', sock)
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except socket.error as ex:
                if ex.errno != errno.ENOTCONN:
                    thesplog('Error during shutdown of socket %s: %s', sock, ex)
            sock.close()


    def protectedFileNumList(self):
        return (list(self._transmitIntents.keys()) +
                list(filter(None, map(self._socketFile,
                                      self._waitingTransmits))) +
                list(self._incomingSockets.keys()) + [self.socket.fileno()])

    def childResetFileNumList(self):
        return self.protectedFileNumList() + \
            [self._openSockets[S].socket.fileno() for S in self._openSockets]

    @staticmethod
    def getAdminAddr(capabilities):
        return ActorAddress(
            (TXOnlyAdminTCPv4ActorAddress
             if capabilities.get('Outbound Only', False) else
             TCPv4ActorAddress)
            (None, capabilities.get('Admin Port', DEFAULT_ADMIN_PORT),
             external=(TCPTransport.getConventionAddress(capabilities) or
                       ('', capabilities.get('Admin Port',
                                             DEFAULT_ADMIN_PORT)) or
                       True)))

    @staticmethod
    def getAddressFromString(addrspec, adminRouting=False):
        if isinstance(addrspec, tuple):
            addrparts = addrspec
        else:
            addrparts = addrspec.split(':')
        addrtype = (RoutedTCPv4ActorAddress if adminRouting else
                    TCPv4ActorAddress)
        return ActorAddress(
            addrtype(addrparts[0],
                     addrparts[1] if addrparts[1:] else DEFAULT_ADMIN_PORT,
                     external=True))

    @staticmethod
    def getConventionAddress(capabilities):
        convAddr = capabilities.get('Convention Address.IPv4', None)
        if not convAddr:
            return None
        try:
            return TCPTransport.getAddressFromString(convAddr)
        except Exception as ex:
            thesplog('Invalid TCP convention address "%s": %s', convAddr, ex,
                     level=logging.ERROR)
            raise InvalidActorAddress(convAddr, str(ex))

    def external_transport_clone(self):
        # An external process wants a unique context for communicating
        # with Actors.
        return TCPTransport(ExternalTransportCopy(),
                            self._adminAddr,
                            self.txOnly,
                            isinstance(self.myAddress.addressDetails,
                                       RoutedTCPv4ActorAddress))


    def _updateStatusResponse(self, resp):
        """Called to update a Thespian_SystemStatus or Thespian_ActorStatus
           with common information
        """
        for each in self._transmitIntents.values():
            resp.addPendingMessage(self.myAddress,
                                   each.targetAddr,
                                   str(each.message))
        for each in self._waitingTransmits:
            resp.addPendingMessage(self.myAddress,
                                   each.targetAddr,
                                   str(each.message))
        for each in self._incomingEnvelopes:
            resp.addReceivedMessage(each.sender,
                                    self.myAddress,
                                    str(each.message))
        asyncTransportBase._updateStatusResponse(self, resp)
        wakeupTransportBase._updateStatusResponse(self, resp)
        for num, each in enumerate(self._openSockets.values()):
            resp.addKeyVal(str(each), 'sock#%d-fd%d' % (num, each.socket.fileno()))

    @staticmethod
    def probeAdmin(addr):
        """Called to see if there might be an admin running already at the
           specified addr.  This is called from the systemBase, so
           simple blocking operations are fine.  This only needs to
           check for a responder; higher level logic will verify that
           it's actually an ActorAdmin suitable for use.
        """
        ss = socket.socket(*addr.addressDetails.socketArgs)
        try:
            ss.setsockopt(socket.SOL_SOCKET,
                          getattr(socket, 'SO_EXCLUSIVEADDRUSE',
                                  socket.SO_REUSEADDR), 1)
            try:
                ss.bind(*addr.addressDetails.bindArgs)
                # no other process bound
                return False
            except socket.error as ex:
                if err_bind_inuse(ex.errno):
                    return True
                # Some other error... not sure if that means an admin
                # is running or not.
                return False  # assume not
        finally:
            ss.close()

    def prepEndpoint(self, assignedLocalAddr, capabilities):
        """In the parent, prepare to establish a new communications endpoint
           with a new Child Actor.  The result of this call will be
           passed to a created child process to use when initializing
           the Transport object for that class; the result of this
           call will also be kept by the parent to finalize the
           communications after creation of the Child by calling
           connectEndpoint() with this returned object.
        """
        if isinstance(assignedLocalAddr.addressDetails, ActorLocalAddress):
            a1, a2 = assignedLocalAddr.addressDetails.addressInstanceNum, None
        else:
            # assumed to be an actual TCPActorAddress-based address
            # (e.g. admin)
            a1, a2 = None, assignedLocalAddr
        return TCPEndpoint(a1, a2,
                           self.myAddress,
                           self._adminAddr,
                           capabilities.get('Admin Routing', False) or
                           capabilities.get('Outbound Only', False),
                           capabilities.get('Outbound Only', False))

    def connectEndpoint(self, endPoint):
        pass

    def deadAddress(self, addressManager, childAddr):
        canceli, continuei = partition(lambda i: i[1].targetAddr == childAddr,
                                       self._transmitIntents.items())
        self._transmitIntents = dict(continuei)
        for _, each in canceli:
            each.socket.close()
            delattr(each, 'socket')
            each.tx_done(SendStatus.DeadTarget)

        canceli, continuei = partition(lambda i: i.targetAddr == childAddr,
                                       self._waitingTransmits)
        self._waitingTransmits = continuei
        for each in canceli:
            each.tx_done(SendStatus.DeadTarget)

        # No need to clean up self._incomingSockets entries: they will
        # timeout naturally.

        super(TCPTransport, self).deadAddress(addressManager, childAddr)

        # Ports may be re-used, so do not set this address to dead in
        # the address manager


    def close_oldest_idle_sockets(self, num_to_close=1):
        aged_keys = sorted([(self._openSockets[K].validity, K)
                            for K in self._openSockets])
        for _,oldkey in aged_keys[:num_to_close]:
            _safeSocketShutdown(self._openSockets.pop(oldkey))

    def new_socket(self, op, *args, **kw):
        try:
            return op(*args, **kw)
        except IOError as ex:
            if err_too_many_open_sockets(ex):
                pass
            else:
                raise
        self.close_oldest_idle_sockets(3)
        return op(*args, **kw)

    _XMITStepSendConnect   = 1
    _XMITStepSendData      = 2
    _XMITStepShutdownWrite = 3
    _XMITStepWaitForAck    = 4
    _XMITStepFinishCleanup = 5
    _XMITStepRetry         = 6

    def serializer(self, intent):
        return toSendBuffer((self.myAddress, intent.message), serializer.dumps)

    def lostRemote(self, rmtaddr):
        """[optional] Called by adminstrative levels (e.g. convention.py) to
           indicate that the indicated remote address is no longer
           accessible.  This is customarily used only by the Admin in
           "Admin Routing" scenarios when the remote is shutdown or
           de-registered to allow the transport to cleanup (e.g. close
           open sockets, etc.).

           This does *not* do anything to remote TXOnly sockets: those
           connections were initiated by the remote and should
           therefore be dropped by the remote.  Dropping those
           connections at this point would be harmful, especially
           because this is typically called when first reconnecting to
           the remote.
        """
        if isinstance(rmtaddr.addressDetails, TXOnlyAdminTCPv4ActorAddress):
            return

        if hasattr(self, '_openSockets'):
            for rmvkey in [each
                           for each in self._openSockets
                           if rmtaddr.addressDetails.isSameSystem(
                                   self._openSockets[each].rmtaddr)]:
                _safeSocketShutdown(self._openSockets[rmvkey])
                del self._openSockets[rmvkey]
        for each in [i for i in self._transmitIntents
                     if rmtaddr.addressDetails.isSameSystem(
                             self._transmitIntents[i].targetAddr)]:
            self._cancel_fd_ops(each)
        for each in [i for i,v in self._incomingSockets.items()
                     if rmtaddr.addressDetails.isSameSystem(
                             v.fromAddress
                             if v.fromAddress.addressDetails else
                             v.socket)]:
            self._cancel_fd_ops(each)

    def _cancel_fd_ops(self, errfileno):
        if errfileno == self.socket.fileno():
            thesplog('SELECT FATAL ERROR ON MAIN LISTEN SOCKET',
                     level=logging.ERROR)
            raise RuntimeError('Fatal listen socket error; aborting')

        if errfileno in self._incomingSockets:
            incoming = self._incomingSockets[errfileno]
            del self._incomingSockets[errfileno]
            incoming = self._handlePossibleIncoming(incoming, errfileno,
                                                    closed=True)
            if incoming:
                self._incomingSockets[incoming.socket.fileno()] = incoming
            return
        if self._processIntents(errfileno, closed=True):
            return
        if self._waitingTransmits:
            W = self._waitingTransmits.pop(0)
            if self._nextTransmitStepCheck(W, errfileno, closed=True):
                self._waitingTransmits.append(W)
            return
        closed_openSocks = []
        for I in getattr(self, '_openSockets', {}):
            if self._socketFile(self._openSockets[I]) == errfileno:
                closed_openSocks.append(I)
        for each in closed_openSocks:
            del self._openSockets[each]

    def interrupt_wait(self,
                       signal_shutdown=False,
                       check_children=False):
        self._shutdownSignalled |= signal_shutdown
        self._checkChildren |= check_children
        # Now generate a spurious connection to break out of the
        # select.select loop.  This is especially useful if a signal
        # handler caused a message to be sent to myself: get the
        # select loop to wakeup and process the message.
        with closing(self.new_socket(
                socket.socket,
                *self.myAddress.addressDetails.socketArgs)) as ts:
            try:
                ts.connect(*self.myAddress.addressDetails.connectArgs)
            except Exception:
                pass

    def _scheduleTransmitActual(self, intent):
        intent = self._forwardIfNeeded(intent)
        if not intent:
            return
        if intent.targetAddr == self.myAddress:
            self._processReceivedEnvelope(ReceiveEnvelope(intent.targetAddr,
                                                          intent.message))
            if not isinstance(intent.message, ForwardMessage):
                self.interrupt_wait()
            return self._finishIntent(intent)
        intent.stage = self._XMITStepSendConnect
        if self._nextTransmitStep(intent):
            if hasattr(intent, 'socket'):
                self._transmitIntents[intent.socket.fileno()] = intent
            else:
                self._waitingTransmits.append(intent)

    def _finishIntent(self, intent, status=SendStatus.Sent):
        if hasattr(intent, 'socket'):
            if hasattr(self, '_openSockets'):
                if not self._queue_intent_extra(intent):
                    if status == SendStatus.Sent:
                        opskey = opsKey(intent.targetAddr)
                        _safeSocketShutdown(self._openSockets.get(opskey, None))
                        self._openSockets[opskey] = IdleSocket(intent.socket,
                                                               intent.targetAddr)
                        # No need to restart a pending transmit for
                        # this target here; the main loop will check
                        # the waitingIntents and find/start the next one
                        # automatically.
                    else:
                        _safeSocketShutdown(intent)
                        # Here waiting intents need to be re-queued
                        # since otherwise they won't run until timeout
                        runnable, waiting = partition(
                            lambda I: I.targetAddr == intent.targetAddr,
                            self._waitingTransmits)
                        self._waitingTransmits = waiting
                        for R in runnable:
                            if status == SendStatus.DeadTarget:
                                R.tx_done(status)
                            elif self._nextTransmitStep(R):
                                if hasattr(R, 'socket'):
                                    thesplog('<S> waiting intent is now re-processing: %s', R.identify())
                                    self._transmitIntents[R.socket.fileno()] = R
                                else:
                                    self._waitingTransmits.append(R)
            else:
                _safeSocketShutdown(intent)
            delattr(intent, 'socket')
        intent.tx_done(status)
        return False  # intent no longer needs to be attempted

    def _queue_intent_extra(self, intent):
        extraRead = getattr(intent, 'extraRead', None)
        if not extraRead:
            return False
        incoming = TCPIncomingPersistent(intent.targetAddr,
                                         intent.socket)
        try:
            incoming.addData(extraRead)
        except Exception:
            # Bad trailing data, so discard it.
            thesplog('discarding bad trailing tx ack data')
            return False
        pendingIncoming = self._addedDataToIncoming(incoming)
        if pendingIncoming:
            self._incomingSockets[
                pendingIncoming.socket.fileno()] = pendingIncoming
        return True  # socket is in-progress or was already handled

    def _forwardIfNeeded(self, intent):
        # Called when an intent is originally received to determine if
        # the target address requires forwarding; if so, wrap the
        # message in a ForwardMessage wrapper and set the routing
        # path.
        if intent.targetAddr == self.myAddress or \
           isinstance(intent.message, ForwardMessage) or \
           not isinstance(intent.targetAddr.addressDetails,
                          RoutedTCPv4ActorAddress):
            return intent

        # Replace None with our local admin and remove this actor
        routing = [A or self._adminAddr
                   for A in intent.targetAddr.addressDetails.routing
                   if A != self.myAddress]

        if self.txOnly and routing and \
           (routing[0] != self._adminAddr) and \
           self.myAddress != self._adminAddr:
            routing.insert(0, self._adminAddr)

        if not routing or routing == [intent.targetAddr]:
            return intent

        if intent.targetAddr.addressDetails.isLocalAddr():
            return intent

        newmsg = ForwardMessage(intent.message,
                                intent.targetAddr,
                                self.myAddress, routing)
        newaddr = newmsg.fwdTargets[0]
        if hasattr(self, '_addressMgr'):
            newaddr, newmsg = self._addressMgr.prepMessageSend(newaddr, newmsg)
            try:
                isDead = newmsg == SendStatus.DeadTarget
            except Exception:
                isDead = False
            if isDead:
                # this is a DeadEnvelope or a ChildActorExited; drop
                # it instead of recursing forever.
                intent.tx_done(SendStatus.Sent)
                return None
        # Changing the target addr to the next relay target for the
        # transmit machinery, but the levels above may process
        # completion based on the original target (e.g. systemCommon
        # _checkNextTransmit), so add a completion operation that will
        # reset the target back to the original (this occurs before
        # other callbacks because callbacks are called in reverse
        # order of addition).
        intent.addCallback(lambda r, i, ta=intent.targetAddr:
                           i.changeTargetAddr(ta))
        intent.changeMessage(newmsg)
        intent.changeTargetAddr(newaddr)
        intent.serMsg = self.serializer(intent)
        return intent

    def _nextTransmitStepCheck(self, intent, fileno, closed=False):
        # Return True if this intent is still valid, False if it has
        # been completed.  If fileno is -1, this means check if there is
        # time remaining still on this intent
        if self._socketFile(intent) == fileno or \
           (fileno == -1 and
            intent.timeToRetry(hasattr(self, '_openSockets') and
                               opsKey(intent.targetAddr) in self._openSockets)):
            if closed:
                intent.stage = self._XMITStepRetry
            return self._nextTransmitStep(intent)
        if intent.expired():
            # Transmit timed out (consider this permanent)
            thesplog('Transmit attempt from %s to %s timed out'
                     ', returning PoisonPacket',
                     self.myAddress, intent.targetAddr, level=logging.WARNING)
            # self._incomingEnvelopes.append(ReceiveEnvelope(intent.targetAddr,
            #                                                PoisonPacket(intent.message)))
            # Stop attempting this transmit
            return self._finishIntent(intent, SendStatus.Failed)
        # Continue to attempt this transmit
        if not intent.delay():
            return self._nextTransmitStep(intent)
        return True

    def _nextTransmitStep(self, intent):
        # Return of True means keep waiting on this Transmit Intent;
        # False means it is done
        try:
            return getattr(self, '_next_XMIT_%s' % intent.stage,
                           '_unknown_XMIT_step')(intent)
        except Exception as ex:
            import traceback
            thesplog('xmit UNcaught exception %s; aborting intent.\n%s',
                     ex, traceback.format_exc(), level=logging.ERROR)
            return False

    def _next_XMIT_1(self, intent):
        if hasattr(self, '_openSockets'):
            opskey = opsKey(intent.targetAddr)
            if opskey in self._openSockets:
                intent.socket = self._openSockets[opskey].socket
                # This intent takes the open socket; there should be only
                # one intent per target but this "take" prevents an
                # erroneous second target intent from causing corruption.
                # The _finishIntent operation will return the socket to
                # the _openSockets list.  It's possible that both sides
                # will simultaneously attempt to transmit, but this should
                # be rare, and the effect will be that neither will get
                # the expected ACK and will close the socket to be
                # re-opened on the next retry period, which is a
                # reasonable approach.
                del self._openSockets[opskey]
                intent.stage = self._XMITStepSendData
                intent.amtSent = 0
                return self._nextTransmitStep(intent)
            # If there is an active or pending Intent for this target,
            # just queue this one (by returning True)
            if any(T for T in self._transmitIntents.values()
                   if T.targetAddr == intent.targetAddr and
                   hasattr(T, 'socket')):
                intent.awaitingTXSlot()
                return True
            # Fall through to get a new Socket for this intent
        if isinstance(intent.targetAddr.addressDetails,
                      TXOnlyAdminTCPv4ActorAddress) and \
           intent.targetAddr != self._adminAddr:
            # Cannot initiate outbound connection to this remote
            # Admin; wait for incoming connection instead.
            intent.backoffPause(True)  # KWQ... not really
            intent.stage = self._XMITStepRetry
            return self._nextTransmitStep(intent)
        intent.socket = self.new_socket(
            socket.socket,
            *intent.targetAddr .addressDetails.socketArgs)
        intent.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        intent.socket.setblocking(0)
        # Disable Nagle to transmit headers and acks asap; our sends
        # are usually small
        intent.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        try:
            intent.socket.connect(*intent.targetAddr
                                         .addressDetails.connectArgs)
            intent.socket.setblocking(0)
        except socket.error as err:
            # EINPROGRESS means non-blocking socket connect is in progress...
            if not err_inprogress(err.errno):
                thesplog('Socket connect failure %s to %s on %s'
                         ' (returning %s)',
                         err, intent.targetAddr, intent.socket,
                         intent.completionCallback,
                         level=logging.WARNING)
                return self._finishIntent(intent,
                                          SendStatus.DeadTarget
                                          if err_conn_refused(err)
                                          else SendStatus.Failed)
        except Exception as ex:
            thesplog('Unexpected TCP socket connect exception: %s', ex,
                     level=logging.ERROR)
            return self._finishIntent(intent, SendStatus.BadPacket)
        intent.stage = self._XMITStepSendData  # When connect completes
        intent.amtSent = 0
        return True

    def _next_XMIT_2(self, intent):
        # Got connected, ready to send
        if not hasattr(intent, 'socket'):
            intent.stage = self._XMITStepRetry
            return self._nextTransmitStep(intent)
        try:
            intent.amtSent += intent.socket.send(
                intent.serMsg[intent.amtSent:])
        except socket.error as err:
            if err_send_inprogress(err.errno):
                intent.backoffPause(True)
                return True
            if err_send_connrefused(err):
                # in non-blocking, sometimes connection attempts are
                # discovered here rather than for the actual connect
                # request.
                thesplog('ConnRefused to %s; declaring as DeadTarget.',
                         intent.targetAddr, level=logging.INFO)
                return self._finishIntent(intent, SendStatus.DeadTarget)
            thesplog('Socket error sending to %s on %s: %s / %s: %s',
                     intent.targetAddr, intent.socket, str(err), err.errno,
                     intent, level=logging.ERROR)
            intent.stage = self._XMITStepRetry
            return self._nextTransmitStep(intent)
        except Exception:
            import traceback
            thesplog('Error sending: %s', traceback.format_exc(),
                     level=logging.ERROR)
            intent.stage = self._XMITStepRetry
            return self._nextTransmitStep(intent)
        if intent.amtSent >= len(intent.serMsg):
            # After data is sent, stop transmit
            intent.stage = self._XMITStepShutdownWrite
        return True

    def _next_XMIT_3(self, intent):
        try:
            pass
            # Original did a socket shutdown for writing, but actual
            # socket implementations aren't so sophisticated and this
            # tended to stop all socket communications in both
            # directions.
            # intent.socket.shutdown(socket.SHUT_WR)
        except socket.error:
            # No shutdown handling, just close
            intent.stage = self._XMITStepFinishCleanup
            return self._nextTransmitStep(intent)
        intent.ackbuf = ReceiveBuffer(serializer.loads)
        intent.stage = self._XMITStepWaitForAck
        return True

    def _next_XMIT_4(self, intent):
        # Actually, select below waited on readable, not writeable
        try:
            rcv = intent.socket.recv(intent.ackbuf.remainingAmount())
        except socket.error as err:
            if err_recv_retry(err.errno):
                intent.backoffPause(True)
                return True
            if err_recv_connreset(err):
                thesplog('Remote %s closed connection before ack received'
                         ' at %s for %s',
                         str(intent.targetAddr), str(self.myAddress),
                         intent.identify(),
                         level=logging.WARNING)
            else:
                thesplog('Socket Error waiting for transmit ack from'
                         ' %s to %s: %s',
                         str(intent.targetAddr), str(self.myAddress), err,
                         level=logging.ERROR, exc_info=True)
            rcv = ''  # Remote closed connection
        except Exception as err:
            thesplog('General error waiting for transmit ack from'
                     ' %s to %s: %s',
                     str(intent.targetAddr), str(self.myAddress), err,
                     level=logging.ERROR, exc_info=True)
            rcv = ''  # Remote closed connection
        if not rcv:
            # Socket closed.  Reschedule transmit.
            intent.backoffPause(True)
            intent.stage = self._XMITStepRetry
            return self._nextTransmitStep(intent)
        return self._check_XMIT_4_done(intent, rcv)

    def _check_XMIT_4_done(self, intent, rcv):
        intent.ackbuf.addMore(rcv)
        if not intent.ackbuf.isDone():
            # Continue waiting for ACK
            return True
        compl = intent.ackbuf.completed()
        if not compl:
            # ACK/NAK was corrupted; retry.
            intent.backoffPause(True)
            intent.stage = self._XMITStepRetry
            return self._nextTransmitStep(intent)
        ackmsg, intent.extraRead = compl
        if isControlMessage(ackmsg):
            intent.result = SendStatus.Sent if ackmsg == ackPacket \
                            else SendStatus.BadPacket
            intent.stage = self._XMITStepFinishCleanup
            return self._nextTransmitStep(intent)
        # Must have received a transmit packet from the remote;
        # process as a received incoming.
        intent.ackbuf.removeExtra()
        if self._addedDataToIncoming(TCPIncomingPersistent(intent.targetAddr,
                                                           intent.socket,
                                                           intent.ackbuf),
                                     True):
            # intent.ackbuf.completed() said ackmsg was a full receive
            # packet, but _addedDataToIncoming disagreed.  This should
            # NEVER HAPPEN.
            thesplog('<<< Should never happen: '
                     'not full receive while waiting for ACK.'
                     ' Aborting socket.',
                     level=logging.CRITICAL)
            intent.ackbuf = ReceiveBuffer(serializer.loads)
            intent.backoffPause(True)
            intent.stage = self._XMITStepRetry
            return self._nextTransmitStep(intent)
        intent.ackbuf = ReceiveBuffer(serializer.loads)
        nxtrcv = intent.extraRead
        intent.extraRead = ''
        return self._check_XMIT_4_done(intent, nxtrcv)

    def _next_XMIT_5(self, intent):
        return self._finishIntent(intent, intent.result)

    def _next_XMIT_6(self, intent):
        if hasattr(intent, 'socket'):
            _safeSocketShutdown(intent)
            delattr(intent, 'socket')
        if hasattr(intent, 'ackbuf'):
            delattr(intent, 'ackbuf')
        if intent.retry():
            intent.stage = self._XMITStepSendConnect
            # stage just set won't be executed until retry delay times out
            return True
        return self._finishIntent(intent, SendStatus.Failed)

    def _processIntents(self, filedesc, closed=False):
        if filedesc in self._transmitIntents:
            intent = self._transmitIntents[filedesc]
            del self._transmitIntents[filedesc]
            if self._nextTransmitStepCheck(intent, filedesc):
                if hasattr(intent, 'socket'):
                    self._transmitIntents[intent.socket.fileno()] = intent
                else:
                    self._waitingTransmits.append(intent)
            return True
        return False

    def _processIntentTimeouts(self):
        procIntents = list(self._transmitIntents.values())
        waitIntents = list(self._waitingTransmits)
        self._transmitIntents = {}
        self._waitingTransmits = []
        for intent in procIntents:
            if hasattr(intent, '_pauseUntil') and not intent.expired():
                self._transmitIntents[intent.socket.fileno()] = intent
                continue
            if self._nextTransmitStepCheck(intent, -1):
                if hasattr(intent, 'socket'):
                    self._transmitIntents[intent.socket.fileno()] = intent
                else:
                    self._waitingTransmits.append(intent)
        for intent in waitIntents:
            if self._nextTransmitStepCheck(intent, -1):
                if hasattr(intent, 'socket'):
                    self._transmitIntents[intent.socket.fileno()] = intent
                else:
                    self._waitingTransmits.append(intent)

    @staticmethod
    def _waitForSendable(sendIntent):
        return sendIntent.stage != TCPTransport._XMITStepWaitForAck

    @staticmethod
    def _socketFile(sendOrRecv):
        return sendOrRecv.socket.fileno() \
            if getattr(sendOrRecv, 'socket', None) else None

    def set_watch(self, watchlist):
        self._watches = watchlist

    def _runWithExpiry(self, incomingHandler):
        xmitOnly = incomingHandler == TransmitOnly or \
                   isinstance(incomingHandler, TransmitOnly)

        if hasattr(self, '_aborting_run'):
            delattr(self, '_aborting_run')

        while not self.run_time.expired() and \
              (not hasattr(self, '_aborting_run') or
               (self._aborting_run and
                (len(self._transmitIntents) > 0 or
                 len(self._waitingTransmits) > 0))):

            if xmitOnly:
                if not self._transmitIntents and not self._waitingTransmits:
                    return 0
            else:
                while self._incomingEnvelopes:
                    rEnv = self._incomingEnvelopes.pop(0)
                    if incomingHandler is None:
                        return rEnv
                    r = Thespian__Run_HandlerResult(incomingHandler(rEnv))
                    if not r:
                        return r

            wsend, wrecv = fmap(
                TCPTransport._socketFile,
                partition(TCPTransport._waitForSendable,
                          filter(lambda T: not T.backoffPause(),
                                 self._transmitIntents.values())))

            wrecv = list(filter(None, wrecv))
            wsend = list(filter(None, wsend))
            wrecv.extend(list(
                filter(lambda I: not self._incomingSockets[I].backoffPause(),
                       filter(None, self._incomingSockets))))

            if hasattr(self, '_openSockets'):
                wrecv.extend(list(map(lambda s: s.socket.fileno(),
                                      self._openSockets.values())))

            delays = list(filter(None,
                                 [self.run_time.remaining()] +
                                 [self._transmitIntents[T].delay()
                                  for T in self._transmitIntents] +
                                 [W.delay() for W in self._waitingTransmits] +
                                 [self._incomingSockets[I].delay()
                                  for I in self._incomingSockets]))
            # n.b. if a long period of time has elapsed (e.g. laptop
            # sleeping) then delays could be negative.
            delay = max(0, timePeriodSeconds(min(delays))) if delays else None

            if not xmitOnly:
                wrecv.extend([self.socket.fileno()])
            else:
                # Windows does not support calling select with three
                # empty lists, so as a workaround, supply the main
                # listener if everything else is pending delays (or
                # completed but unrealized) here, and ensure the main
                # listener does not accept any listens below.
                if not wrecv and not wsend:
                    if not hasattr(self, 'dummySock'):
                        self.dummySock = socket.socket(socket.AF_INET,
                                                       socket.SOCK_DGRAM,
                                                       socket.IPPROTO_UDP)
                    wrecv.extend([self.dummySock.fileno()])

            if self._watches:
                wrecv.extend(self._watches)

            rrecv, rsend, rerr = [], [], []
            try:
                rrecv, rsend, rerr = select.select(wrecv, wsend,
                                                   set(wsend+wrecv), delay)
            except ValueError as ex:
                thesplog('ValueError on select(#%d: %s, #%d: %s, #%d: %s, %s)',
                         len(wrecv), wrecv, len(wsend), wsend,
                         len(set(wsend + wrecv)), set(wsend + wrecv),
                         delay, level=logging.ERROR)
                raise
            except (OSError, select.error) as ex:
                errnum = getattr(ex, 'errno', ex.args[0])
                if err_select_retry(errnum):
                    # probably a change in descriptors
                    thesplog('select retry on %s', ex, level=logging.DEBUG)
                    self._check_indicators()
                    continue
                if err_bad_fileno(errnum):
                    # One of the selected file descriptors was bad,
                    # but no indication which one.  It should not be
                    # one of the ones locally managed by this
                    # transport, so it's likely one of the
                    # user-supplied "watched" file descriptors.  Find
                    # and remove it, then carry on.
                    if errnum == errno.EBADF:
                        bad = []
                        for each in self._watches:
                            try:
                                _ = select.select([each], [], [], 0)
                            except:
                                bad.append(each)
                        if not bad:
                            thesplog('bad internal file descriptor!')
                            try:
                                _ = select.select([self.socket.fileno()], [], [], 0)
                            except:
                                thesplog('listen %s is bad', self.socket.fileno)
                                rerr.append(self.socket.fileno)
                            for each in wrecv:
                                try:
                                    _ = select.select([each], [], [], 0)
                                except:
                                    thesplog('wrecv %s is bad', each)
                                    rerr.append(each)
                            for each in wsend:
                                try:
                                    select.select([each], [], [], 0)
                                except:
                                    thesplog('wsend %s is bad', each)
                                    rerr.append(each)
                        else:
                            self._watches = [W for W in self._watches if W not in bad]
                            continue
                    # If it was a regular file descriptor, fall through to clean it up.
                else:
                    raise

            if rerr:
                for errfileno in rerr:
                    self._cancel_fd_ops(errfileno)

            origPendingSends = len(self._transmitIntents) + \
                               len(self._waitingTransmits)

            # Handle newly sendable data
            for eachs in rsend:
                self._processIntents(eachs)

            # Handle newly receivable data
            for each in rrecv:
                # n.b. ignore this if trying to quiesce; may have had
                # to supply this fd to avoid calling select with three
                # empty lists.
                if each == self.socket.fileno() and not xmitOnly:
                    self._acceptNewIncoming()
                    continue
                # Get idleSockets before checking incoming and
                # transmit; those latter may modify _openSockets
                # (including replacing the element) so ensure that
                # only the sockets indicated by select are processed,
                # and only once each.
                idleSockets = list(getattr(self, '_openSockets', {}).values())

                if each in self._incomingSockets:
                    incoming = self._incomingSockets[each]
                    del self._incomingSockets[each]
                    incoming = self._handlePossibleIncoming(incoming, each)
                    if incoming:
                        self._incomingSockets[
                            incoming.socket.fileno()] = incoming
                    continue

                if self._processIntents(each):
                    continue

                for idle in idleSockets:
                    rmtaddr = idle.rmtaddr
                    curOpen = self._openSockets.get(opsKey(rmtaddr), None)
                    if curOpen and curOpen != idle:
                        # duplicate sockets to remote, and this one is
                        # no longer tracked, so close it and keep
                        # existing openSocket.
                        _safeSocketShutdown(idle)
                    else:
                        fnum = None
                        try:
                            fnum = idle.socket.fileno()
                        except IOError as ex:
                            if not err_bad_fileno(ex.errno):
                                raise
                        if fnum is None or each == fnum:
                            del self._openSockets[opsKey(rmtaddr)]
                            incoming = self._handlePossibleIncoming(
                                TCPIncomingPersistent(rmtaddr, idle.socket),
                                each)
                            if incoming:
                                self._incomingSockets[
                                    incoming.socket.fileno()] = incoming
                        elif idle.expired():
                            _safeSocketShutdown(idle)
                            del self._openSockets[opsKey(rmtaddr)]

            # Handle timeouts
            self._processIntentTimeouts()
            rmvIncoming = []
            for I in self._incomingSockets:
                newI = self._handlePossibleIncoming(self._incomingSockets[I],
                                                    -1)
                if newI:
                    # newI will possibly be new incoming data, but
                    # it's going to use the same socket
                    self._incomingSockets[I] = newI
                else:
                    rmvIncoming.append(I)
            for I in rmvIncoming:
                del self._incomingSockets[I]

            watchready = [W for W in self._watches if W in rrecv]
            if watchready:
                self._incomingEnvelopes.append(
                    ReceiveEnvelope(self.myAddress, WatchMessage(watchready)))

            # Check if it's time to quit
            if [] == rrecv and [] == rsend:
                if [] == rerr and self.run_time.expired():
                    # Timeout, give up
                    return Thespian__Run_Expired()
                continue
            if xmitOnly:
                remXmits = len(self._transmitIntents) + \
                           len(self._waitingTransmits)
                if origPendingSends > remXmits or remXmits == 0:
                    return remXmits

            # Handle queued internal "received" data
            if not xmitOnly:
                while self._incomingEnvelopes:
                    rEnv = self._incomingEnvelopes.pop(0)
                    if incomingHandler is None:
                        return rEnv
                    r = Thespian__Run_HandlerResult(incomingHandler(rEnv))
                    if not r:
                        return r

        return Thespian__Run_Terminated() \
            if hasattr(self, '_aborting_run') else \
            Thespian__Run_Expired()

    def _check_indicators(self):
        if self._checkChildren:
            self._checkChildren = False
            self._incomingEnvelopes.append(
                ReceiveEnvelope(self.myAddress, ChildMayHaveDied()))
        if self._shutdownSignalled:
            self._shutdownSignalled = False
            self._incomingEnvelopes.append(
                ReceiveEnvelope(self.myAddress, ActorExitRequest()))

    def _acceptNewIncoming(self):
        accepted = False
        try:
            lsock, rmtTxAddr = self.new_socket(self.socket.accept)
            accepted = True
        except (OSError, socket.error) as ex:
            thesplog('Error accepting incoming: %s', ex)
        self._check_indicators()
        if not accepted or rmtTxAddr == self.myAddress:
            self._incomingEnvelopes.append(Thespian__UpdateWork())
        if not accepted:
            return
        lsock.setblocking(0)
        # Disable Nagle to transmit headers and acks asap
        lsock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Note that the TCPIncoming is initially None.
        # Due to the way sockets work, the transmit comes from a
        # system-selected port that is different from the port that
        # the remote Actor (or admin) is listening on (and which
        # represents it's official ActorAddress).  Once a successful
        # message has been received, the message will indicate the
        # originating address and the TCPIncoming object will be
        # updated accordingly.
        self._incomingSockets[lsock.fileno()] = (
            (TCPIncomingPersistent
             if hasattr(self, '_openSockets') else
             TCPIncoming)
            (ActorAddress(None), lsock))

    def _handlePossibleIncoming(self, incomingSocket, fileno, closed=False):
        if closed:
            # Remote closed, so unconditionally drop this socket
            incomingSocket.close()
            return None
        elif incomingSocket.socket and \
             (incomingSocket.socket.fileno() == fileno or
              not incomingSocket.delay()):
            return self._handleReadableIncoming(incomingSocket)
        else:
            if not incomingSocket.delay():
                # No more delay time left
                incomingSocket.close()
                return None
            return incomingSocket

    def _finishIncoming(self, incomingSocket, fromRealAddr):
        # Only called if incomingSocket can continue to be used; if
        # there was an error then incomingSocket should be closed and
        # released.
        fromAddr = incomingSocket.fromAddress
        if fromAddr and isinstance(incomingSocket, TCPIncomingPersistent):
            opskey = opsKey(fromAddr)
            _safeSocketShutdown(self._openSockets.get(opskey, None))
            self._openSockets[opskey] = IdleSocket(incomingSocket.socket,
                                                   fromAddr)
            for T in self._transmitIntents.values():
                if T.targetAddr == fromAddr and T.stage == self._XMITStepRetry:
                    T.retry(immediately=True)
                    # This intent will be picked up on the next
                    # timeout check in the main loop and
                    # processed; by waiting for main loop
                    # processing, fairness with read handling is
                    # allowed.
                    break
        else:
            incomingSocket.close()
        return None

    def _handleReadableIncoming(self, inc):
        try:
            rdata = inc.socket.recv(min(8192, inc.remainingSize()))
            inc.failCount = 0
        except socket.error as e:
            inc.failCount = getattr(inc, 'failCount', 0) + 1
            if err_recv_inprogress(e.errno) and \
               inc.failCount < MAX_CONSECUTIVE_READ_FAILURES:
                inc.backoffPause(True)
                return inc
            inc.close()
            return None
        if not rdata:
            # Since this point is only arrived at when select() says
            # the socket is readable, this is an indicator of a closed
            # socket.  Since previous calls didn't detect
            # receivedAllData(), this is an aborted/incomplete
            # reception.  Discard it.
            inc.close()
            return None
        try:
            inc.addData(rdata)
        except Exception:
            # Bad data, so discard it and close the socket.
            thesplog('corrupted incoming data; closing socket',
                     level=logging.WARNING)
            inc.close()
            return None
        return self._addedDataToIncoming(inc)

    def _addedDataToIncoming(self, inc, skipFinish=False):
        if not inc.receivedAllData():
            # Continue running and monitoring this socket
            return inc
        rdata, extra = '', ''
        try:
            rdata, extra = inc.data
            if isControlMessage(rdata):
                raise ValueError('Error: received control message'
                                 ' "%s"; expecting incoming data.' %
                                 (str(rdata)))
            rEnv = ReceiveEnvelope(*rdata)
        except Exception:
            import traceback
            thesplog('OUCH!  Error deserializing received data:'
                     ' %s  (rdata="%s", extra="%s")',
                     traceback.format_exc(), rdata, extra)
            try:
                inc.socket.send(ackDataErrMsg)
            except Exception:
                pass  # socket will be closed anyhow; AckErr was a courtesy
            inc.close()
            return None
        try:
            inc.socket.send(ackMsg)
        except socket.error as err:
            if err_send_connreset(err):
                thesplog('Remote %s closed socket before ACK could be sent',
                         inc.socket, level=logging.WARNING)
            else:
                raise
        inc.fromAddress = rdata[0]
        self._processReceivedEnvelope(rEnv)
        if extra and isinstance(inc, TCPIncomingPersistent):
            newinc = TCPIncomingPersistent(inc.fromAddress, inc.socket)
            try:
                newinc.addData(rdata)
            except Exception:
                # Bad trailing data, so discard it by doing nothing.
                thesplog('discarding bad incoming trailing data')
                pass
            else:
                return self._addedDataToIncoming(newinc)
        if not skipFinish:
            self._finishIncoming(inc, rEnv.sender)
        return None

    def _processReceivedEnvelope(self, envelope):
        if not isinstance(envelope.message, ForwardMessage):
            self._incomingEnvelopes.append(envelope)
            return
        if envelope.message.fwdTo == self.myAddress:
            self._incomingEnvelopes.append(
                ReceiveEnvelope(envelope.message.fwdFrom,
                                envelope.message.fwdMessage))
            return
        # The ForwardMessage has not reached the final destination, so
        # update and target it at the next one.
        if len(envelope.message.fwdTargets) < 1 and \
           envelope.message.fwdTo != self.myAddress:
            thesplog('Incorrectly received ForwardMessage destined for'
                     ' %s at %s via %s: %s',
                     envelope.message.fwdTo, self.myAddress,
                     list(map(str, envelope.message.fwdTargets)),
                     envelope.message.fwdMessage,
                     level=logging.ERROR)
            # discard  (TBD: send back as Poison? DeadLetter? Routing failure)
            return
        nextTgt = envelope.message.fwdTargets[0]
        envelope.message.fwdTargets = envelope.message.fwdTargets[1:]
        self.scheduleTransmit(getattr(self, '_addressMgr', None),
                              TransmitIntent(nextTgt, envelope.message))

    def abort_run(self, drain=False):
        self._aborting_run = drain
