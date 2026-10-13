# dod

`dod` is a cross-platform test client for DODP v1 (DAISY Online Delivery Protocol) backends. It acts as a Reading System against any conforming Service.

## Language

**Service**:
A DODP backend that implements the protocol and is addressed by one SOAP endpoint URL.
_Avoid_: Server, API

**Reading System**:
The DODP role `dod` plays towards a Service; it identifies itself to the Service through `setReadingSystemAttributes`.
_Avoid_: Client, agent

**Session**:
The stateful relationship between a Reading System and a Service, from a successful `logOn` until `logOff` or expiry on the Service side. It is carried by an opaque HTTP cookie.
_Avoid_: Login, connection

**Initialisation sequence**:
The mandatory `logOn`, `getServiceAttributes`, `setReadingSystemAttributes` calls that make a Session usable.
_Avoid_: Handshake

**Session file**:
The local record of one Session, identified by Service URL and username, that lets separate `dod` invocations reuse it. It never holds a password.
_Avoid_: Cache, token file

**Expired session**:
A Session the Service no longer recognises, signalled by a `noActiveSession` fault.
_Avoid_: Invalid session, stale cookie

**Ephemeral mode**:
Running a command with its own Session that is never persisted and is ended with `logOff` afterwards.
_Avoid_: Stateless mode
