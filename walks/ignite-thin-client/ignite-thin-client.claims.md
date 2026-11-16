# Claims ledger: Apache Ignite 2.17.0 thin client walk

Walk: `ignite-thin-client.walk.json` (id `ignite-2.17.0-thin-client`). Project: Apache Ignite 2.17.0, commit
d53d4540b64bb4a25f1a5a1003c4338727628c9f, read from `demo/ignite-2.17.0` (read only). Written 2026-11-16 by reading the
source; nothing was built or run (no Maven, no Java except PlantUML).

Paths below are relative to the project root. `core/...` abbreviates `modules/core/src/main/java/org/apache/ignite/...`
and `coretest/...` abbreviates `modules/core/src/test/java/org/apache/ignite/...`. Sources: `code file:lines`,
`README or docs` (README, DEVNOTES, javadoc prose), `build file`, or `inference` (reasoned from code that was read, not
run). "How checked" says what was read; "read" means the whole method or block including early returns and error paths.

## Chapter 1: Overview

| Phrase | Claim (spoken text) | Source | Exceptions and limits | How checked |
|---|---|---|---|---|
| c1.p1 | This walk explains the Apache Ignite 2.17.0 thin client to an engineer who must debug it, in about twenty-one minutes plus the stops. | inference (walk length) | Length estimated from word count at 135 words/min + 0.7 s gaps; actual clip lengths unknown until narrated | Counted words in the final JSON (see end) |
| c1.p3 | The README calls Ignite a distributed database for high-performance computing with in-memory speed. | README `README.md:14` | Marketing text, stated as the README's words | Read README.md fully (50 lines) |
| c1.p4 | Its feature list includes distributed key-value storage, SQL, the structured query language, and compute and service grids. | README `README.txt:7-17` | It is a list in a README; the phrase names four of its ten items; not verified feature by feature | Read README.txt lines 1-60 |
| c1.p5 | Disk storage is optional: native persistence in a data region stays off unless you enable it. | code `core/configuration/DataRegionConfiguration.java:137-140` (`persistenceEnabled = false`) | Per data region; README says disk tier optional (`README.md:29`) | Read field and javadoc |
| t1.p1 | This schema, drawn from the 2.17.0 code, shows Ignite's server nodes and how clients reach them. | inference (diagram d1) | Diagram labels individually ledgered below | n/a |
| t1.p2 | Nodes find each other through discovery. If you configure none, Ignite uses TcpDiscoverySpi. | code `core/internal/IgnitionEx.java:2001-2003` | Default only; any DiscoverySpi may be configured (e.g. ZooKeeper module exists) | Read `initializeDefaultSpi` 2001-2020 |
| t1.p4 | Messages between nodes travel through the communication service, by default TcpCommunicationSpi. | code `core/internal/IgnitionEx.java:2012-2013` | Default only | Same method |
| t1.p7 | A thick client is a full node in client mode; its discovery documentation says it routes discovery traffic through one server node. | docs (javadoc) `core/spi/discovery/tcp/TcpDiscoverySpi.java:130-133` | Javadoc, not traced in code; `forceServerMode` can change it (line 134-136); phrase says "the discovery documentation says" | Read class javadoc 124-140 |
| t1.p8 | Three kinds of remote clients share one server listener, the client connector: the thin client and the drivers for JDBC, Java Database Connectivity, and ODBC, Open Database Connectivity. | code `core/internal/processors/odbc/ClientListenerNioListener.java:465-481` (`prepareContext` switch over ODBC/JDBC/THIN) | JDBC/ODBC sides not walked; only the switch and the client-type constants (`ClientListenerNioListener.java:58-65`: 0 ODBC, 1 JDBC, 2 thin) were read | Read `prepareContext`, `ensureClientPermissions` |
| t1.p10 | REST, representational state transfer, over HTTP, the hypertext transfer protocol, starts only when the rest-http module is on the class path. | code `core/internal/processors/rest/GridRestProcessor.java:995-1014` (`Class.forName(HTTP_PROTO_CLS)`; ClassNotFound -> debug log only) | REST processor also has a TCP protocol (ConnectorConfiguration, port 11211) not mentioned in the phrase | Read `startHttpProtocol` |
| t1.p11 | The thin client is not a node: it builds its own small network layer for TCP connections, transmission control protocol, to client connectors. | code `GridNioClientConnectionMultiplexer.java:75-110` (builds the client-mode GridNioServer) | "builds" (T07): the connections themselves are opened in `open` (142-198), called from `TcpClientChannel.java:210`; no discovery class is referenced under internal/client/thin (grep) | Read constructor and open; grep |
| t1.p12 | An application starts one with Ignition.startClient, which hands the configuration to TcpIgniteClient. | code `core/Ignition.java:584-588` | Throws NPE for null cfg (585) | Read method |

## Chapter 2: Preparations

| Phrase | Claim (spoken text) | Source | Exceptions and limits | How checked |
|---|---|---|---|---|
| c2.p1 | The code is Apache Ignite 2.17.0, at the commit recorded with this walk; the parent build file sets the version, and Java 11 source level. | build file `parent/pom.xml:48-52` | The `java-15+` profile (parent/pom.xml 1001-1010) keeps source 11 but sets target 15 on JDK 15+; the phrase says source level only. Commit is from the walk's project record, not from the tree | Read properties and both Java profiles |
| c2.p3 | The developer notes give the full build through the Maven wrapper, mvnw: clean install with the all-java and licenses profiles, skipping tests. | docs `DEVNOTES.txt:13-17` | Wrapper is configured for Maven 3.8.3 (`.mvn/wrapper/maven-wrapper.properties:18`); `-Pall-java` adds examples, benchmarks etc. (pom.xml 73-84) | Read DEVNOTES 1-120, pom.xml modules/profiles, wrapper properties |
| c2.p5 | The test commands here set the property named fork count set to one, so tests run forked and get the Java module options. | build file `parent/pom.xml:889-903` (profile activated by property presence) | "so that the options reach the tests": inference from Maven Surefire behaviour (argLine applies to forked JVMs); the argLine is in the `java-11+` profile (parent/pom.xml 942-957, JDK [11,15)) and the `java-15+` profile (1050-1081) | Read profile and both surefire argLines |
| c2.p7 | To run a server node, the notes describe a release build that leaves a binary zip under target bin. | docs `DEVNOTES.txt:28-32` | DEVNOTES says to run it after the full build; zip name pattern `apache-ignite-<version>-bin.zip`; the node action then uses `bin/ignite.sh` (row c2.p8 below) | Read DEVNOTES |
| t2.p1 | This schema maps the thin-client code in the 2.17.0 source tree. | inference (diagram d2) | Labels ledgered below | n/a |
| t2.p2 | The public API, the application programming interface, is the package org.apache.ignite.client, starting with the IgniteClient interface. | code `core/client/IgniteClient.java:35` | Also exceptions, retry policies, events (directory listing) | ls of the package; read interface |
| t2.p3 | The implementation is the internal package client.thin, led by TcpIgniteClient, which implements that interface. | code `core/internal/client/thin/TcpIgniteClient.java:86-91` |  | Read class header and fields |
| t2.p5 | On the server, the listener lives in the processors.odbc package; despite the name, it also serves JDBC and thin clients. | code `ClientListenerNioListener.java:465-481` | Package name is historical (inference about naming, phrase says only "despite the name") | Read `prepareContext` |
| t2.p6 | Thin-client specifics live in processors.platform.client: connection context, message parser, request handler, and the request classes. | code `core/internal/processors/platform/client/ClientMessageParser.java:460-474` | Some op codes share a class (e.g. three cursor page codes -> ClientCacheQueryNextPageRequest, 488-493), so "a request class per operation" is approximate; phrase says "a request class per operation" | Read `decode` switch 460-738 |
| t2.p7 | FunctionalTest in the same module starts a server node and a client in one Java process, handy for debugging both sides. | code `coretest/internal/client/thin/FunctionalTest.java:275-280` (`Ignition.start(Config.getServerConfiguration())` + `Ignition.startClient`) | FunctionalTest is parameterized (useBinaryArrays), so each test runs twice | Read testPutGet 270-350, class header, AbstractBinaryArraysTest |
| c2.p10 | Every server node starts a client connector by default: the node configuration holds a default connector configuration. | code `core/configuration/IgniteConfiguration.java:585` | Turned off by `setClientConnectorConfiguration(null)` with no deprecated SQL/ODBC configs (`ClientListenerProcessor.java:549-550`) - not narrated | Read field and `prepareConfiguration` 543-606 |
| c2.p12 | ClientConnectorConfiguration defaults: port 10800 with a range of 100, a ten-second handshake timeout, and an idle timeout of zero, meaning none. | code `core/configuration/ClientConnectorConfiguration.java:31-56` | Idle 0 -> `Long.MAX_VALUE` in `ClientListenerProcessor.java:197`; GridNioServer's own idle check not read | Read constants and fields 28-128 |
| c2.p14 | It also turns thin clients, JDBC and ODBC on or off, all on by default, and holds the SSL, Secure Sockets Layer, settings. | code `ClientConnectorConfiguration.java:97-113` | Enforcement in `ensureClientPermissions` (ClientListenerNioListener 508-536). Inconsistency (rule 5), not spoken: the javadoc of `thinCliEnabled` (line 103) says "JDBC connections enabled flag", a copied comment; the code uses the field for thin clients (`isThinClientEnabled`, 525-530) | Read fields and enforcement |
| c2.p15 | ThinClientConfiguration sets limits: one hundred active transactions per connection, and zero compute tasks. | code `core/configuration/ThinClientConfiguration.java:28-38` | Also `sendServerExcStackTraceToClient` default false (41) | Read class |
| c2.p16 | With zero, the server refuses thin-client compute with a functionality disabled error. | code `core/internal/processors/platform/client/ClientConnectionContext.java:344-349` | Only caller: `compute/ClientExecuteTaskRequest.java:81` (grep) | Read method; grep callers |
| c2.p17 | On the client, an address without a port expands to every port from 10800 to 10900. | code `core/internal/client/thin/ClientDiscoveryContext.java:224-237` | Only when no address finder is set; IPv6 handled by HostAndPortRange.parse | Read `parsedAddresses`, `HostAndPortRange.parse` 52-112 |
| c2.p18 | Each port is a separate endpoint, so one address without a port gives a hundred and one endpoints. | code `ClientDiscoveryContext.java:244-248` (`singletonList` per port) | After discovery, endpoints from the server replace these (getEndpoints 213-216) | Read; checked inclusive range `rangeClosed` |
| c2.p19 | The timeout defaults to zero, which means wait without limit. | code `core/configuration/ClientConfiguration.java:60-61` | Used as connect timeout (multiplexer 92, 152) and sync wait (TcpClientChannel 424, 742); not for async calls | Read field and its uses |
| c2.p20 | Partition awareness and cluster discovery are on, reconnects are throttled to three per thirty seconds, and the retry policy agrees to every retry. | code `ClientConfiguration.java:117-148` | "agrees to every retry": `ClientRetryAllPolicy.java:28-29` returns true; the policy is consulted only after connection errors of public operations (`ReliableChannel.java:951-980`); throttling disabled when either value is 0 (javadoc 135-138) | Read fields; `ClientRetryAllPolicy.java:23-31` |
| c2.p21 | Heartbeats are off by default. | code `ClientConfiguration.java:153-157` | Interval 30 s when on | Read fields |

## Chapter 3: Main design ideas

| Phrase | Claim (spoken text) | Source | Exceptions and limits | How checked |
|---|---|---|---|---|
| t3.p1 | This schema shows the protocol frames as the 2.17.0 code writes and reads them. | inference (d3) | Labels ledgered below | n/a |
| t3.p2 | Design idea one: a binary protocol over TCP. Every message starts with a four-byte length that does not count itself. | code `TcpClientChannel.java:385-394` (`req.writeInt(0, req.position() - 4)`) | Same for handshake (873) and server side (`ClientMessage.java:93-97` writes msgSize of payload) | Read send, handshakeReq; server ClientMessage writeTo/readFrom |
| t3.p3 | Numbers are little-endian, whatever the machine. | code `core/internal/client/thin/io/gridnioserver/GridNioClientParser.java:51-52` | Comment + `order(LITTLE_ENDIAN)` on decode; encoding side relies on binary streams (not traced further) | Read decode |
| t3.p4 | A request then holds a two-byte operation code, an eight-byte request id, and the payload. | code `TcpClientChannel.java:387-392` | Handshake has no request id (849-856) | Read send |
| t3.p6 | A cache payload starts with the cache id and a flags byte; expiry durations, then a transaction id, follow only when flagged. | code `TcpClientCache.java:1478-1509` | Order on the wire: expiry durations (1501-1505), then the transaction id (1507-1508) (K14); expiry needs protocol 1.6.0 (1488-1491); server reads in the same order (`ClientCacheRequest.java:58-68`, `ClientCacheDataRequest.java:40-44`) | Read writer and server readers |
| t3.p7 | A response starts with the request id. From protocol version 1.4.0, two bytes of flags follow: error, topology changed, and notification. | code `TcpClientChannel.java:530-560` | For notifications the first long is a resource id (`ClientNotification.java:82`) | Read processNextMessage fully |
| t3.p8 | With the topology flag, the new topology version follows; with the error flag, a status code and a message follow. | code `core/internal/processors/platform/client/ClientResponse.java:82-101` | Topology version = int64 + int32 (`ClientAffinityTopologyVersion.java:63-68`); flag values `ClientFlag.java:48-55` | Read encode; client read side 539-583 |
| t3.p10 | The first message must be a handshake of at most 64 mebibytes, whose first three bytes are the handshake code and major version one or two. | code `core/internal/processors/odbc/ClientMessage.java:154-186` | First three bytes must be 1,1,0 or 1,2,0 (`HANDSHAKE_HEADER`, `HANDSHAKE_HEADER2`, 41-45; check 172-186), else IOException "Handshake header check failed"; size must be > 0 and at most 64 MiB (154-158) (K16); a non-handshake first command is also closed (`ClientListenerNioListener.java:355-361`) | Read readFrom and constants |
| c3.p2 | Design idea two: version and features are agreed per connection. The client proposes protocol version 1.7.0 and can fall back to 1.0.0. | code `TcpClientChannel.java:102-115` |  | Read constants; `ProtocolVersion.java:22-47` |
| c3.p5 | The handshake carries the version, client type two, the client's feature bitmask, user attributes, and the user name and password if set. | code `TcpClientChannel.java:849-873` | Mask and attributes only when the proposed version has bitmask features (1.7.0); credentials only from 1.1.0 and when user non-empty (866-871) | Read handshakeReq and protocolContextFromVersion |
| c3.p7 | The reply carries the agreed features and, from 1.4.0, the server's node id. | code `TcpClientChannel.java:749-760` (client reads features and node id) | Server side writes them in `ClientRequestHandler.java:175-183`; "agreed": the server's set is the client's mask limited to features the server knows, minus TX_AWARE_QUERIES when disabled (`ClientConnectionContext.java:192-203`, row c3.p6 below); the client adopts that set (755) | Read both sides |
| c3.p8 | If the server refuses the version, it names its own; the client retries with it if supported, and otherwise fails. | code `TcpClientChannel.java:789-819` | If server version equals proposed -> plain ClientProtocolError (789-790); if server < 1.1.0 and user set -> mismatch (792) | Read handshake loop 714-839 |
| c3.p9 | A wrong password raises a client authentication exception, which is not a connection error, so no other server is tried. | code `TcpClientChannel.java:784-788` | "no other server": inference with paths - ClientAuthenticationException extends ClientException, not ClientConnectionException (`core/client/ClientAuthenticationException.java:23`); ReliableChannel catches only ClientConnectionException (865, 879, 795, 924) | Read class hierarchy and all catch blocks in ReliableChannel |
| c3.p11 | Design idea three: requests share a connection. Each channel numbers requests from one and keeps the pending ones by id. | code `TcpClientChannel.java:135-139` | Handshake uses internal id -1, not sent (716) | Read fields, send, handshake |
| c3.p12 | On the server, each message goes to a thread pool, so requests from one connection can finish out of order. | code `core/internal/util/nio/GridNioAsyncNotifyFilter.java:93-105` | Pool is `execSvc` = thin client executor (`ClientListenerProcessor.java:156, 361`); "finish out of order": inference (no per-session ordering seen in the filter); cancellation path for JDBC (370-401) does not apply to thin client (`ClientRequestHandler.isCancellationSupported` false, 191) | Read filter, makeFilters, handler |
| c3.p14 | A synchronous call waits on its future, with the configured timeout when it is above zero. | code `TcpClientChannel.java:417-442` (timed wait and its catch) | Timeout 0 = untimed get (424); the catch converts and rethrows (434-441) (T02) | Read receive |
| c3.p15 | If that timeout fires, the call fails with a plain client exception: no retry, and the connection stays open. | code `TcpClientChannel.java:489-515` (default branch) | Inference with paths: `pendingReq.get(timeout)` throws IgniteFutureTimeoutCheckedException (extends IgniteCheckedException, `core/internal/IgniteFutureTimeoutCheckedException.java:26`), cause null -> line 515; ReliableChannel catches only ClientConnectionException; nothing closes the channel in receive. The pending map entry is not removed on timeout (a late response is still consumed) | Read receive, convertException, ReliableChannel catches |
| c3.p15a | Nothing tells the server to stop: a timed-out put may still be applied, and its late reply goes unused. | code `TcpClientChannel.java:585-592` (a late reply is still matched by id and completes a future nobody waits on) | No cancel exists: receive's catch only converts and rethrows (434-441), the pending entry is not removed on timeout, and the thin-client handler reports no cancellation support (`ClientRequestHandler.java:190-193`); "may still be applied": inference, the server processes the request independently of the client's wait (K10). The connect and handshake waits use the same timeout (multiplexer 92/152, TcpClientChannel 742) - not spoken | Read receive, processNextMessage, handler |
| c3.p16 | An asynchronous call only registers a listener, so it has no client-side timeout at all. | code `TcpClientChannel.java:452-481` | Future completes on response or when the channel closes (293-302) | Read receiveAsync; searched for a timer in async path (none) |
| c3.p18 | Design idea four: partition awareness. With a current partition map, a key operation goes straight to the node the map names; otherwise the reliable channel picks one. | code `ReliableChannel.java:340-357` | "the reliable channel picks one" (K01): `applyOnDefaultChannel` (815-852) tries a random open channel first when partition awareness is on and more than one channel is open, else the current default holder; details in t8.p17a | Read affinityService |
| c3.p20 | Design idea five: failover. After a connection error the call moves to another server, while attempts remain and the retry policy agrees. | code `ReliableChannel.java:879-889` | "another server": after a failure the default holder moves on (`rollCurrentChannel` 494-515) and the next attempt uses it (838-839); system ops always retried (951-959) | Read applyOnDefaultChannel fully |
| c3.p21 | Design idea six: security is optional. The server authenticates a client only when security is enabled on the node. | code `core/internal/processors/odbc/ClientListenerAbstractConnectionContext.java:108-129` | null security context -> IgniteAccessControlException "The user name or password is incorrect" (125-128) | Read |
| c3.p23 | The handshake sends the user name and password as plain strings: without SSL they cross the network in clear text. | code `TcpClientChannel.java:866-871` | Inference: the only encryption in the client pipeline is GridNioSslFilter (multiplexer 82-90) | Read handshakeReq and multiplexer filters |
| c3.p24 | On the client, SSL stays off until you set an SSL mode other than disabled. | code `core/internal/client/thin/ClientSslUtils.java:79-81` | Default `SslMode.DISABLED` (`ClientConfiguration.java:73`); a context factory alone does not enable SSL, it is consulted only after the DISABLED check (83-92) (K13) | Read getSslContext and the field |
| c3.p25 | On the server, sslEnabled adds an SSL filter, by default with the node's SSL context factory; sslClientAuth demands client certificates. | code `ClientListenerProcessor.java:410-426` | Null factory -> "SSL is enabled but factory is null" (414-416); `wantClientAuth` and `needClientAuth` both set to the flag | Read makeFilters |
| c3.p27 | A security exception in a request reaches the client as a client authorization exception. | code `TcpClientChannel.java:574-577` | Server side: SecurityException -> SECURITY_VIOLATION status (`ClientRequestHandler.java:117-122`); the request runs in the connection's security context (`ClientListenerNioListener.java:218-220`) (K13) | Read both sides |
| c3.p28 | Compared with the Ignite interface, IgniteClient has no data streamer, events, messaging, locks, latches, semaphores, queues or atomic sequences. | code `core/client/IgniteClient.java:158-254` (the non-cache facilities) | Compared with the method names of `core/Ignite.java`; the cache methods (44-155) have no near-cache variant either, but near caches were dropped from the spoken list when the range was narrowed (T01) | Listed public methods of both interfaces |
| c3.p30 | Compute takes a task name, not code, so the task class must already be on the servers. | code `core/client/ClientCompute.java:49` | "must already be on the servers": inference (only a name crosses the wire); peer class loading not examined; default off from c2.p15/c2.p16 | Read interface methods |

## Chapter 4: Modules

| Phrase | Claim (spoken text) | Source | Exceptions and limits | How checked |
|---|---|---|---|---|
| t4.p1 | This schema shows the client-side classes of 2.17.0 in call order. | inference (d4) | Labels ledgered below | n/a |
| t4.p2 | TcpIgniteClient is the facade; its constructor builds the binary marshaller and the reliable channel, then connects. | code `TcpIgniteClient.java:138-158` | Then `retrieveBinaryConfiguration` (158); failure closes the channel and rethrows (183-186) | Read constructor 134-187 |
| t4.p3 | TcpClientCache is a light handle: asking the client for a cache by name sends nothing to the server. | code `TcpIgniteClient.java:239-243` | `getOrCreateCache` does send CACHE_GET_OR_CREATE_WITH_NAME (199-205); TcpClientCache constructor only registers custom affinity locally (`TcpClientCache.java:153`, `ReliableChannel.java:415-422`) | Read `cache`, `getOrCreateCache`, TcpClientCache constructor |
| t4.p4 | So a wrong cache name fails only at the first operation, when the server says the cache does not exist. | code `core/internal/processors/platform/client/cache/ClientCacheRequest.java:154-162` | Status CACHE_DOES_NOT_EXIST = 1000 (`ClientStatus.java:50`); inference: first operation is the first server contact (t4.p3) | Read cacheDescriptor |
| t4.p7 | TcpClientChannel is one TCP connection: it holds the socket, numbers the requests and keeps their futures until the responses arrive. | code `TcpClientChannel.java:132-139` (socket, request id counter, pending map) | Futures are completed in processNextMessage (585-592); the handshake is in `handshake` (714-839), no longer claimed here (T03) | Read fields |
| t4.p8 | All channels of one client share one multiplexer, a GridNioServer in client mode with a single selector. | code `GridNioClientConnectionMultiplexer.java:94-110` (`.selectorCount(1)`) | One multiplexer per ReliableChannel (`ReliableChannel.java:150-151`), passed to every channel (1079) | Read both |
| t4.p12 | When the client writes a binary type it has not registered yet, it first sends a separate put binary type request. | code `TcpIgniteClient.java:609-623` | Chain marshal -> `BinaryClassDescriptor` -> `BinaryContext.updateMetadata` -> `addMeta` (`core/internal/binary/BinaryContext.java:1358-1359`, `BinaryClassDescriptor.java:855,875`); postponed until the channel exists (618); also sent when metadata changed | Read handler; grep the call chain |
| t5.p1 | This schema shows the server side in 2.17.0, from the socket to the cache and back. | inference (d5) |  | n/a |
| t5.p2 | ClientListenerProcessor starts a GridNioServer named client-listener, with the connector's selector count. | code `ClientListenerProcessor.java:182-200` |  | Read start() |
| t5.p3 | Incoming bytes pass the SSL filter if SSL is on, then the codec filter, which builds one client message per frame. | code `ClientListenerProcessor.java:408-438` | Order from `core/internal/util/nio/GridNioFilterChain.java:50-52` (listener <- filters[0] <- ... <- head); filters array is {openSesFilter, codecFilter, sslFilter} | Read makeFilters and chain constructor |
| t5.p4 | Then the async notify filter hands each message to the processor's executor. | code `ClientListenerProcessor.java:359-361` (the notify filter is built with `execSvc`) | `execSvc` = the node's thin-client executor (156); the filter's `onMessageReceived` hands the message to its worker pool (`GridNioAsyncNotifyFilter.java:93-104`); the JDBC cancellation branch (370-401) is not taken for thin clients (T04) | Read makeFilters, start, filter |
| t5.p4a | That executor is the client-connector pool, sized by the connector's thread pool size, with an unbounded queue. | code `core/internal/processors/pool/PoolProcessor.java:545-555` | `getThinClientExecutorService` returns this pool (897-899); it exists only when a connector configuration is set (545) | Read |
| t5.p5 | ClientListenerNioListener receives it: with no connection context yet, it is the handshake; afterwards, a request to decode and handle. | code `ClientListenerNioListener.java:162-185` | Decode failure -> "Failed to parse client request." and session close (186-199) | Read onMessage fully |
| t5.p8 | ClientRequestHandler runs a request directly or, if it is asynchronous, waits briefly and otherwise answers when its future completes. | code `ClientRequestHandler.java:127-150` | Wait default 10 ms, system property IGNITE_THIN_CLIENT_ASYNC_REQUESTS_WAIT_TIMEOUT (51-58); <= 0 -> no wait | Read handle, handle0 |
| t5.p10 | Cache key requests are asynchronous only on transactional caches; the code comment says such operations can block the thread. | code `ClientCacheKeyRequest.java:66-70` | Comment is the code's own reasoning, quoted as such | Read |
| t5.p11 | Cache key requests, such as put and get, use the server's cache in keep-binary mode, so keys and values stay binary there. | code `ClientCacheRequest.java:76-78` | Key requests use `cache(ctx)` (`ClientCachePutRequest.java:40`, `ClientCacheGetRequest.java:41`). Not every cache request (K04): scan, index and continuous queries use `rawCache(ctx)` when a Java filter is given and keep-binary was not requested (`ClientCacheScanQueryRequest.java:77-78`, `ClientCacheIndexQueryRequest.java:158-159`, `ClientCacheQueryContinuousRequest.java:83-85`); get-configuration uses rawCache only to read the configuration (48) | Read |
| t5.p14 | When a client disconnects, the server cleans up its resources and closes its open transactions. | code `ClientConnectionContext.java:247-251` | Chain: `super.onDisconnected` -> `cleanupTxs` -> `ClientTxContext.close` -> `tx.close()` (ClientListenerAbstractConnectionContext 133-138, ClientConnectionContext 325-330, tx/ClientTxContext.java 102-114); whether close rolls back was not traced | Read chain |

## Chapter 5: Workflows

| Phrase | Claim (spoken text) | Source | Exceptions and limits | How checked |
|---|---|---|---|---|
| t6.p1 | This sequence, drawn from the 2.17.0 code, shows the connect and the handshake. | inference (d6) |  | n/a |
| t6.p3 | channelsInit takes its endpoints from the discovery context; before any discovery, those are the configured addresses. | code `ClientDiscoveryContext.java:198-212` | Holders are built from these endpoints in `initChannelHolders` (`ReliableChannel.java:618-739`, `getEndpoints` call at 626) (T06); an address finder, if set, is asked every time (202-203) | Read getEndpoints and initChannelHolders |
| t6.p5 | Then it connects the default holder: a new TcpClientChannel tries the holder's addresses in turn until a socket opens. | code `TcpClientChannel.java:202-221` | Connect failure -> info log "Can't establish connection with" and next address; all fail -> exception (243-247) | Read constructor |
| t6.p7 | On the server, each new connection gets a handshake timer, ten seconds by default; without a handshake in time, the session closes with a warning. | code `ClientListenerNioListener.java:302-317` | Scheduled only if timeout > 0 (`onConnected` 136-144); cancelled only on success (391); a failed handshake leaves the timer running | Read |
| t6.p8 | The server reads the version and client type, builds the connection context, and checks the type is enabled and the version supported. | code `ClientListenerNioListener.java:363-389` | Unsupported -> "Unsupported version" (389) | Read onHandshake 342-455 |
| t6.p9 | initializeFromHandshake reads the features, attributes and credentials, authenticates, and creates the request handler and message parser. | code `ClientConnectionContext.java:188-234` | Credentials read only if bytes remain (211-224) | Read |
| t6.p11 | On success the server cancels the timer and replies true, its features and node id; on failure, false, a version, a message and a status. | code `ClientListenerNioListener.java:391-454` | "a version" (K15): the server's default version 1.7.0, or 0.0.0 after a failed authentication (417-419) or when no context could be created for the client type (434-435); status only for client version >= 1.1.0; the session is not closed on failure | Read |
| t6.p13 | The holder then registers the reliable channel as a topology listener, and files the channel under the server's node id. | code `ReliableChannel.java:1079-1095` | Only if the server sent a node id (protocol >= 1.4.0), line 1081 | Read getOrCreateChannel |
| t6.p14 | With partition awareness on, channelsInit then starts connecting all other holders in the background. | code `ReliableChannel.java:770-774` (`if (partitionAwarenessEnabled) initAllChannelsAsync();`) | The task itself: 560-579 (T05) | Read channelsInit and initAllChannelsAsync |
| t6.p15 | That task ignores the reconnect throttle: an address without a port can cost a hundred and one connect attempts, each failure a warning with a logger set. | code `ReliableChannel.java:565-575` | Throttle ignored via `getOrCreateChannel(true)` (570); "can cost" (K09): the loop stops when the channel is closed or a newer reinit started (566-567), and discovery may replace the 101 configured holders after the first topology change; warnings only with a logger set (default NullLogger); inference combining c2.p18 with this loop | Read both |
| t6.p17 | The server flags the first response on each connection as topology changed, since it has reported no version there yet. | code `ClientConnectionContext.java:280-296` (`oldVer == null`) | Every ClientResponse.encode calls it (`ClientResponse.java:109-111`); notifications do not (ClientNotification.encode) | Read |
| t6.p18 | That reaches onTopologyChanged, which, in the background, refreshes the server endpoints and, with partition awareness, runs channelsInit again. | code `ReliableChannel.java:586-606` | Only if the topology version is newer than the last one seen (590); without partition awareness reinit waits for the default channel to fail (551-553) | Read |
| c5.p1 | To watch this, debug the put and get functional test, starting at TcpClientChannel.handshake and ClientListenerNioListener.onHandshake; the action lists the rest. | action (see Actions) | Two breakpoints spoken (T08); the action lists handshakeReq, initializeFromHandshake, writeHandshake as well | Method names verified in code |
| c5.p2 | For client logs, set a logger in the configuration; without one, the client uses a null logger and stays silent. | code `TcpIgniteClient.java:138` | Same pattern in ReliableChannel 138, TcpClientChannel 188; the attached action also sets event listeners (`ConnectionEventListener.java:23-48`, `RequestEventListener.java:27-41`, row c5.p3 below) | Read |
| c5.p4 | On the server, a refused version, client type or recovery mode logs the warning error during handshake; a wrong password only logs client authentication failed, at debug level. | code `ClientListenerNioListener.java:397-428` | K03: the version, client type and recovery refusals throw IgniteCheckedException subclasses (389, 512-534, `ClientConnectionNodeRecoveryException extends IgniteCheckedException`) and reach the warn branch (426-428); `IgniteAccessControlException` (also an IgniteCheckedException) is caught first (406) and logged only at debug (409-413); success logs at debug (397-404) | Read onHandshake catches and exception classes |
| c5.p4a | After a refused handshake, such as a wrong password, the server may later warn of a handshake timeout too: the timer started at connect is cancelled only on success. | code `ClientListenerNioListener.java:386-406` (cancel at 391, inside the success path, before the catches at 406) | Timer started in `onConnected` (136-144) when the handshake timeout is above 0; `cancelHandshakeTimeout` has this one caller (grep: 323 definition, 391 call); the timeout task logs the warning without checking the session state (305-313); "may": not run (K11) | Read; grep |
| c5.p12 | The client connections system view lists each node's open client connections, and the control script can print it. | code `ClientListenerProcessor.java:228-233` | View name `client.connections` (80); control command `--system-view` (`core/internal/management/SystemViewCommand*.java`; tests use `--system-view` and `--all-nodes`) | Read; checked test constants |
| t7.p1 | This sequence, drawn from the 2.17.0 code, follows a put and a get from the client API to the cache and back. | inference (d7) |  | n/a |
| t7.p2 | ClientCache put rejects a null key or value, then runs a single-key operation with the cache put code. | code `TcpClientCache.java:183-196` |  | Read |
| t7.p4 | Outside a transaction, a keyed call goes to affinityService on the reliable channel; inside one, to the transaction's own channel. | code `TcpClientCache.java:1366-1382` | tx clear operations refused (1369, 1423-1426) | Read txAwareService |
| t7.p6 | The chosen channel's send takes the next request id, registers a future under it, and writes the frame to the session. | code `TcpClientChannel.java:353-398` | Closed channel -> "Channel is closed" before registering (366-373); on error the pending entry is removed (400-408) | Read |
| t7.p7 | On the server, a client-connector thread decodes the frame and, for the put code, builds a ClientCachePutRequest. | code `ClientMessageParser.java:437-474` | Thread: c3.p12 row | Read |
| t7.p9 | For an atomic cache the request runs on this thread and calls put on the server's IgniteCache; this walk stops there. | code `ClientCachePutRequest.java:39-43` | Transactional: processAsync path (t5.p10) | Read |
| t7.p10 | Before that, outside transactions, it counts whether this node is primary for the key, on partitioned caches with statistics on: a check of partition awareness. | code `ClientCacheKeyRequest.java:73-95` | Only outside a transaction (`!isTransactional()`, 74) (K17); exceptions ignored (90-92); metric descriptions say they count affinity-aware key requests sent to the primary node or not (`ClientListenerMetrics.java:96-100`) | Read |
| t7.p12 | The put answers with a bare header: with flags in use and no error, just the request id and flags. | code `ClientResponse.java:74-95` | Topology version added when changed (89-90) | Read |
| t7.p13 | On the client's selector thread, processNextMessage matches the id, removes the pending future and completes it, waking the caller. | code `TcpClientChannel.java:585-592` | "selector thread": `GridNioClientListener.onMessage` -> `GridNioClientConnection.onMessage` -> `TcpClientChannel.onMessage` with no executor in between (GridNioClientListener 51-57); that GridNioServer calls listeners on its worker thread is inference from GridNio's design (not read in GridNioServer) | Read chain |
| t7.p14 | get takes the same path with the cache get code, and no value in the request. | code `TcpClientCache.java:157-167` |  | Read |
| t7.p15 | On the server, ClientCacheGetRequest calls get and wraps the value in a ClientObjectResponse. | code `core/internal/processors/platform/client/cache/ClientCacheGetRequest.java:40-44` | Value written after the header (`ClientObjectResponse.java:41-45`) | Read |
| t7.p17 | The client then deserializes the value, unless the cache handle keeps binary. | code `ClientUtils.java:572-580` |  | Read |
| c5.p5 | If processing throws, the server logs failed to process client request, and sends back a status code and a message. | code `ClientListenerNioListener.java:266-284` | Error (not Exception) logged at error level and rethrown (275-283) | Read handleError and handleException |
| c5.p6 | It adds the server's stack trace only when configured to, which is off by default. | code `ClientRequestHandler.java:153-171` | "It" = the server's error reply; distributed property can override the static setting (`ClientListenerProcessor.java:665-670`); default false (`ThinClientConfiguration.java:40-41`) | Read |
| c5.p7 | On the client, the error arrives as a ClientServerError with that status code, as the cause of a ClientException. | code `TcpClientChannel.java:578-582` | Wrapping in convertException (489-491); SECURITY_VIOLATION handled separately (574-577) | Read |
| c5.p8 | Breakpoints for this path: TcpClientCache.put on the client and ClientCachePutRequest.process0 on the server; the action lists the rest. | action | Two breakpoints spoken (T08); the action lists affinityService, send, processNextMessage, onMessage, decode, handle0, process0, encode | Method names verified |
| c5.p9 | With trace logging for ClientListenerNioListener, the server logs each request received and processed, with id and duration. | code `ClientListenerNioListener.java:205-255` | Only at trace level (207, 250) | Read |
| t8.p1 | This sequence, drawn from the 2.17.0 code, shows how a key finds its node, and what happens when a node is lost. | inference (d8) |  | n/a |
| t8.p3 | Without a current mapping for the cache, missing or older than the last topology, one thread at a time refetches it in its own call; others go without. | code `ReliableChannel.java:437-486` | K05: an update is due when there is no current mapping for the cache: missing (`ClientCacheAffinityContext.java:124-128`), or `currentMapping` null because the topology is outdated (no open channel to its nodes, 318-331) or newer than the mapping (284); the CAS winner fetches synchronously within its own call (453-458); the others get false (485) and take the fallback channel choice; no last topology -> false (443-444); all nodes fail -> warning and reset (470-476) | Read |
| t8.p4 | The server maps only partitioned caches with the default rendezvous affinity and no custom key mapper, unless custom mappings are requested. | code `ClientCachePartitionsRequest.java:184-203` | Inactive cluster -> error (84-85); caches without an assignment are skipped (148-150) | Read process and helpers |
| t8.p6 | To place a key, the client converts it to binary and takes its affinity key field, if its type has one configured. | code `ClientCacheAffinityMapping.java:86-108` | If the binary key is not a BinaryObjectExImpl -> no node (102-103) | Read |
| t8.p7 | The default mapper computes the partition with the rendezvous formula, and the map turns the partition into a primary node id. | code `ClientCacheAffinityMapping.java:328-347` | "primary": the server's mapping lists primary partitions per node (`ClientCachePartitionMapping.java:38-49`); custom mappers when a factory is configured and the server sends custom mappings (`ClientCacheAffinityMapping.java:207-208`) | Read |
| t8.p9 | The mapping is used only while a channel to at least one node of the last topology is open. | code `ClientCacheAffinityContext.java:318-331` | Also requires mapping version >= last topology (`currentMapping` 273-288) | Read |
| t8.p10 | With a node id, the reliable channel uses that node's channel; without one, it chooses a channel as for any other call. | code `ReliableChannel.java:911-935` | Without a node channel: `applyOnDefaultChannel(function, op, failures)` with no failures yet (935) - random open channel first or the default holder (K01) | Read |
| t8.p11 | If the node's channel fails, the client records it and, unless one attempt is the limit, asks the retry policy before trying another channel. | code `ReliableChannel.java:924-935` | With `attemptsLimit == 1` the failure is thrown without asking the policy (930) (K06); the failure counts toward the fallback's attempts (935) | Read |
| t8.p12 | When a server goes away, its channel closes, and every pending request fails with a connection exception: channel is closed. | code `TcpClientChannel.java:281-302` | Chain `GridNioClientListener.onDisconnected` -> `GridNioClientConnection.onDisconnected` -> `TcpClientChannel.onDisconnected` (268-276); notification listeners also told (304-314) | Read |
| t8.p13 | The reliable channel catches only connection exceptions: it logs channel failure, closes the channel, runs fail listeners, and moves the default on. | code `ReliableChannel.java:530-544` | Closes only if the holder still holds that channel (538) | Read onChannelFailure, rollCurrentChannel |
| t8.p15 | Then the policy decides: system operations, with no public type, are always retried; public ones only if the policy agrees. | code `ReliableChannel.java:951-964` | Policy exception -> no retry, suppressed (976-979) | Read shouldRetry; ClientOperation.toPublicOperationType default null (523-524) |
| t8.p16 | The default policy agrees to everything, writes included: a put whose connection broke may already be applied, and is sent again. | code `core/client/ClientRetryAllPolicy.java:23-31` | "may already be applied": inference - the request may have been sent before the connection failed; no server-side deduplication found (request ids are per connection, start at 1 on each new channel) | Read policy and send |
| t8.p16a | To avoid that, ClientRetryReadPolicy agrees only for reads, and ClientRetryNonePolicy never agrees. | code `core/client/ClientRetryReadPolicy.java:23-49` | CACHE_PUT is not in the list, so it falls to `return false` (47); `ClientRetryNonePolicy.java:28-29` returns false. "never agrees" is about the policy's answer: system operations are retried without asking it (`ReliableChannel.java:954-958`), and t8.p21/t8.p21a name two more paths that bypass it (K12) | Read both policies and shouldRetry |
| t8.p17 | The number of attempts is the number of holders, or the retry limit when that is above zero and smaller. | code `ReliableChannel.java:939-948` |  | Read |
| t8.p17a | With partition awareness on and several channels open, the first try goes to a random open channel, with one extra attempt. | code `ReliableChannel.java:820-852` | Random choice only when no failure has been recorded in this call (838); the extra attempt when partition awareness is on and more than one channel is open (824-825) (K06, K01) | Read applyOnDefaultChannel |
| t8.p19 | When every attempt has failed and no channel is open, the client resets discovery to the configured addresses and rebuilds its holders. | code `ReliableChannel.java:546-550` | Condition: `channelsCnt == 0 && failures == attemptsLimit`; "to configured addresses": reset sets UNKNOWN_TOP_VER so getEndpoints uses configured addresses (`ClientDiscoveryContext.java:88-92, 202-212`) | Read |
| t8.p21 | One path differs: in a synchronous call with partition awareness on, a broken open channel is reconnected and the call repeated once; only a further failure reaches the policy. | code `ReliableChannel.java:858-889` | K02: only when the function throws ClientConnectionException synchronously - the async function never does (`TcpClientChannel.serviceAsync` 335-345 returns a failed future; `applyOnClientChannelAsync` 266-302); only when the holder's channel existed before the call (`c0 == c`, 858/866); the reconnect goes through `getOrCreateChannel()` with throttling (1075-1077); a failure of the reconnect or of the repeat lands in the outer catch (879-889), which asks the policy | Read applyOnDefaultChannel, async helpers, holder |
| t8.p21a | Asynchronous calls have no such repeat, and when they cannot connect, they move to the next holder without asking the policy. | code `ReliableChannel.java:245-250` (the async path passes `null` as the operation) | Consequence at 887: `op != null && !shouldRetry(...)` - with a null operation a failure to get a channel never asks the policy and the loop moves on while attempts remain; failures after sending are judged by the policy in `applyOnClientChannelAsync` (290). Inconsistency (rule 5), not spoken: the comment at 229 says "Use the only one attempt" while the code retries | Read serviceAsync, handleServiceAsync, applyOnClientChannelAsync, applyOnDefaultChannel |
| t8.p22 | Transactions do not fail over: their operations use the transaction's channel, where a connection error ends with transaction context has been lost. | code `TcpClientCache.java:1366-1377` | Async variant 1397-1410 not read in full | Read |
| c5.p10 | Breakpoints here: ReliableChannel.applyOnDefaultChannel and onChannelFailure; the action lists the rest and the tests that exercise them. | code `ReliableChannel.java:815-820` (applyOnDefaultChannel) | Two breakpoints spoken (T08); the action lists affinityInfoIsUpToDate, applyOnNodeChannelWithFallback, shouldRetry and the tests | Method names verified |
| c5.p10a | With a client logger, a failed partition map update logs failed to update cache partitions mapping; a success logs at debug level. | code `ReliableChannel.java:460-471` | Warning at 470-471, debug line at 461-463; other failover log lines (536 Channel failure, 956 Retrying system operation, 972 Retry policy returned) are in the action (T09) | Read |

## Chapter 6: Notes and open questions

| Phrase | Claim (spoken text) | Source | Exceptions and limits | How checked |
|---|---|---|---|---|
| c6.p1 | Some notes. The client's tcpNoDelay setting is stored but never used: the client's network layer always turns TCP no-delay on. | code `GridNioClientConnectionMultiplexer.java:105-110` (`.tcpNoDelay(true)`) | grep `isTcpNoDelay` under internal/client/thin: only stored in ClientChannelConfiguration (125, 170), no reader | grep |
| c6.p2 | Flow control is loose: the client sets no limit on pending requests. | code `TcpClientChannel.java:138-139` | Server queue from t5.p4 | Read; searched for a bound (none) |
| c6.p2a | On the server, only the optional session outbound queue limit, off by default, disconnects a client that reads too slowly. | code `ClientListenerProcessor.java:680-693` | Default limit 0 = none (`ClientConnectorConfiguration.java:61-62, 121-127`); the size listener is installed only when the limit is above 0 (175-178) (K07) | Read |
| c6.p3 | The server's idle timeout is off by default; when set, idle sessions are closed, so clients then need heartbeats. | code `ClientListenerNioListener.java:286-289` | Advice backed by `coretest/client/ReliabilityTest.java:666` (testServerDoesNotDisconnectIdleClientWithHeartbeats), not run | Read |
| c6.p4 | Durability, replication and consistency come from the cache, not the thin client: the put response follows the server's cache call. | code `ClientCachePutRequest.java:39-48` | Async (transactional) path: response after the future completes (47) | Read; cache side out of scope |
| c6.p5 | The thin-client code carries no to-do or fix-me markers, on either side. | grep over internal/client/thin, processors/platform/client, odbc/ClientListener*.java, odbc/ClientMessage.java | grep for TODO and FIXME: no hits | grep |
| c6.p6 | Open question. With heartbeats on, the channel asks for the idle timeout inside its constructor, before the reliable channel registers as its topology listener. | code `TcpClientChannel.java:253-255` | Listener added after the constructor returns (`ReliableChannel.java:1079-1082`) | Read both |
| c6.p7 | That reply would carry the one-time topology flag, so partition awareness might stay idle until the topology changes; a test with heartbeats on would show it. | inference from `ReliableChannel.java:1079-1082`, `ClientConnectionContext.java:280-296`, `TcpClientChannel.java:539-547` | Labelled as an open question in the phrase; not tested | Read |
| c6.p8 | Also, the endpoint branch in channelsInit runs only if no channel is open just after the default one connected, so a normal start skips it. | code `ReliableChannel.java:759-769` | Spoken as a note, no longer as an open question (K08); endpoints are refreshed from onTopologyChanged (586-606, t6.p18) | Read channelsInit, all channelsInit callers (549, 553, 602, TcpIgniteClient 156) and the counter updates |
| c6.p9 | Not covered: the JDBC, ODBC and other language clients; timings and real failover need a running cluster. | scope statement | Rephrased without first person (T10) |  |

## Checked, not spoken

Claims that were checked and then cut from the spoken text for length (some cut again in the review round:
c3.p1, t4.p6, t6.p2). They stay here because diagram labels, actions or other rows rely on them.

| Former phrase | Claim | Source | Exceptions and limits | How checked |
|---|---|---|---|---|
| c3.p1 | Design idea one: a light client. Its reliable channel keeps connection holders, a partition map and the server endpoints. | code `core/internal/client/thin/ReliableChannel.java:68-93` | Also holds counters, locks, listeners; "light" is a characterisation | Read all fields 64-120 |
| t4.p6 | A ClientChannelHolder stands for one endpoint list. It opens its channel only when needed, and throttles reconnects. | code `ReliableChannel.java:1062-1079` | Throttling: at most `reconnectThrottlingRetries` per period (1034-1049); background init ignores it (570) | Read ClientChannelHolder fully |
| t6.p2 | TcpIgniteClient creates the reliable channel and calls its channelsInit method. | code `TcpIgniteClient.java:151-156` |  | Read |
| t1.p9 | Client type byte: 0 ODBC, 1 JDBC, 2 thin client | code `ClientListenerNioListener.java:58-65` | Unknown type -> "Unknown client type" error (478-480) | Read constants and switch |
| c2.p4 | By default tests run inside the Maven process: surefire forkCount 0 | build file `parent/pom.xml:527-531` | Surefire also depends on `ignite-tools` (parent/pom.xml 460-469), so a prior install is needed | Read plugin config 455-545 |
| c2.p8 | ignite.sh uses config/default-config.xml unless another file is passed | code `bin/ignite.sh:59-61` and `bin/include/parseargs.sh` (non-option argument becomes CONFIG) | `-v` sets IGNITE_QUIET=false, `-J<opt>` adds JVM options (parseargs.sh) - used in actions | Read ignite.sh 40-175 and parseargs.sh |
| c2.p13 | Node binds the first free port of the range and logs "Client connector processor has started on TCP port N" | code `core/internal/processors/odbc/ClientListenerProcessor.java:180-205` | Loop stops at 65535; failure to bind any -> IgniteCheckedException "Failed to bind to any [host:port]" (220-223); log only if INFO enabled | Read `start()` 132-249 |
| c3.p3 | Version features: authentication 1.1.0, partition awareness 1.4.0, transactions 1.5.0, bitmask features 1.7.0 | code `core/internal/client/thin/ProtocolVersionFeature.java:33-52` | Also query entity precision 1.2.0, expiry policy and cluster API 1.6.0 (not narrated) | Read class |
| c3.p4 | Since then capabilities are bits in a mask; 20 defined | code `ProtocolBitmaskFeature.java:29-90` (ids 0-19) | Server enum `ClientBitmaskFeature` lists the same 20 ids | Read both enums |
| c3.p6 | Server keeps features it knows; drops TX_AWARE_QUERIES if disabled | code `ClientConnectionContext.java:192-203` | `ClientBitmaskFeature.enumSet` only maps known ids (`ThinProtocolFeature.enumSet`, not read in detail) | Read initializeFromHandshake |
| c3.p10 | Node in recovery mode: channel closes socket and tries holder's next address | code `TcpClientChannel.java:226-237` | Only if `X.hasCause(e, ClientConnectionNodeRecoveryException)`; other handshake connection errors are rethrown (227-228) | Read constructor 184-256 |
| c3.p13 | Client matches responses by id; unknown id -> protocol error | code `TcpClientChannel.java:585-592` | Notifications are matched by resource id to listeners instead (593-619) | Read |
| c3.p22 | Security enabled by built-in authentication or a security plugin; both -> node refuses to start | code `core/internal/IgniteKernal.java:1396-1406` | Built-in: `createComponent` returns IgniteAuthenticationProcessor when authenticationEnabled (3355-3356); "refuses to start": the IgniteCheckedException is thrown while starting processors (inference: not traced to process exit) | Read securityProcessor and createComponent |
| c3.p29 | Server decodes data streamer requests; Java client has no such operation | code `ClientMessageParser.java:657-661` | Java client: grep for STREAMER in `ClientOperation.java` - no hits | Read; grep |
| t4.p5 | ReliableChannel owns holders, default channel, retries, partition awareness | code `ReliableChannel.java:61-81` |  | Read class |
| t4.p11 | Keys and values in Ignite binary format by the client's marshaller | code `ClientUtils.java:540-542` |  | Read |
| t5.p7 | Parser maps op code to request class; unknown code -> invalid op code error, connection stays | code `ClientMessageParser.java:732-737` | Also: in recovery mode non-startup requests get "Node in recovery mode." (448-449) | Read decode and its fall-through |
| t5.p13 | Slow reader: responses queue; only the outbound queue limit (off by default) disconnects | code `ClientListenerProcessor.java:680-693` | Default 0 = no limit (`ClientConnectorConfiguration.java:61-62, 121-127`); listener registered only when limit > 0 (175-178) | Read |
| t6.p6 | Connect uses the client timeout; with SSL, waits for SSL handshake | code `GridNioClientConnectionMultiplexer.java:149-192` | timeout 0 = no connect timeout (JDK socket semantics, not Ignite code) | Read open |
| t6.p12 | Heartbeats if on and agreed: ask idle timeout, interval = a third, at least 0.5 s, never more than configured | code `TcpClientChannel.java:941-963` | Enabled only if `HEARTBEAT` feature and config flag (253-255); idle timeout <= 0 -> configured interval (944-950); heartbeat sent only if nothing was sent within the interval (1010-1011); failures ignored (1013-1015) | Read |
| t6.p16 | Client fetches binary configuration when auto binary configuration is on and server supports it | code `TcpIgniteClient.java:550-558` | Custom name mapper mismatch -> IgniteClientException (588-593) | Read |
| c5.p3 | Event listeners: handshake start/success/fail, connection closed; request listeners per request | code `core/client/events/ConnectionEventListener.java:23-48` | Request listener methods `RequestEventListener.java:27-41`; invoked from TcpClientChannel (383, 430, 765, 809...) | Read interfaces and call sites |
| t7.p3 | Payload: cache id and flags, key, value | code `TcpClientCache.java:1439-1445` |  | Read cacheSingleKeyOperation |
| t7.p11 | Walk does not follow into cache internals | scope statement |  | n/a |
| t8.p2 | Missing cache in mapping -> marked pending, update due | code `ClientCacheAffinityContext.java:121-131` |  | Read |
| t8.p5 | Mapping lists primary partitions per node | code `ClientCachePartitionMapping.java:38-49` |  | Read |
| t8.p18 | Partition awareness and > 1 open channel: one extra attempt; first try on a random open channel | code `ReliableChannel.java:820-852` | Random choice only on the first try (838) | Read |
| t8.p20 | Caller gets first failure, later ones suppressed | code `ReliableChannel.java:892-905` |  | Read composeException |
| c5.p11 | Metrics count affinity key requests hitting or missing the primary | code `core/internal/processors/odbc/ClientListenerMetrics.java:46-50` | Counted only as in t7.p10; registry name from `GridMetricManager.CLIENT_CONNECTOR_METRICS` = metricName("client","connector") | Read |

## Diagram labels (rule 13)

Every diagram title says "drawn from the 2.17.0 code" (d2: "source tree").

**d1-ignite-overview**

| Label | Source | Check |
|---|---|---|
| Discovery / TcpDiscoverySpi by default / (default port 47500) | `IgnitionEx.java:2002-2003`; `TcpDiscoverySpi.java:247` `DFLT_PORT = 47500` | Read |
| Communication / TcpCommunicationSpi by default / (default port 47100) | `IgnitionEx.java:2012-2013`; `TcpCommunicationSpi.java:224` | Read |
| Caches, SQL, compute, services | `Ignite.java:122,181,436` (compute, services, cache); SQL modules indexing/calcite (`pom.xml:54,69`) | Read signatures, pom |
| Native persistence (off unless enabled) | `DataRegionConfiguration.java:140` | Read |
| Client connector (default port 10800) | `ClientConnectorConfiguration.java:32` | Read |
| REST over HTTP (only with the rest-http module; Jetty port 8080 by default) | `GridRestProcessor.java:1000-1014`; `modules/rest-http/.../GridJettyRestProtocol.java:249` (`IGNITE_JETTY_PORT` default "8080", used when no Jetty config URL) | Read |
| Thick client node (client mode); joins through discovery | `IgniteConfiguration.java:2603`; javadoc `TcpDiscoverySpi.java:130-133` | Read |
| client type 0 / 1 / 2 on the arrows | `ClientListenerNioListener.java:58-65` | Read |
| discovery and communication (between nodes) | default SPIs above | Read |
| Note: not a cluster node; it opens its own TCP connections to client connectors | as t1.p11 | grep + read |

**d2-source-layout**: package names and class names checked by directory listing of `core/client`,
`core/internal/client/thin`, `.../thin/io`, `core/internal/processors/odbc`, `core/internal/processors/platform/client`,
`coretest/client` (ConnectionTest, ReliabilityTest), `coretest/internal/client/thin` (FunctionalTest,
ThinClientPartitionAwareness*Test), `modules/platforms/cpp/thin-client`, `modules/platforms/dotnet/Apache.Ignite.Core/Impl/Client`.
"GridNioServer in client mode" = t1.p11. "(shared with JDBC and ODBC)" = t1.p8. "TCP" arrow = t1.p11.

**d3-wire-format** (field order is a claim)

| Box / line | Source |
|---|---|
| title: all numbers little-endian | `GridNioClientParser.java:51-52` |
| Handshake request: length not counting itself; byte 1; int16 major, minor, patch; byte 2; feature bitmask (1.7.0+); user attributes map (1.7.0+); user name, password (1.1.0+, only if set) | `TcpClientChannel.java:849-873`; `ClientListenerRequest.HANDSHAKE` = 1 confirmed by server check (`ClientListenerNioListener.java:353-355`, `ClientMessage.java:41-45`); attributes written when the proposed context has USER_ATTRIBUTES, i.e. version with bitmask features (883-888) |
| Handshake response success: bool, feature bitmask (1.7.0+), server node id (1.4.0+) | `ClientRequestHandler.java:175-183`; client read `TcpClientChannel.java:747-760` |
| Handshake response failure: server version or 0.0.0, message, int32 status (1.1.0+) (review fix K15) | `ClientListenerNioListener.java:415-424` (0.0.0 after a failed authentication), 432-451 (default version 1.7.0, or 0.0.0 when no context was created); client read 773-779 |
| Request: int32 length, int16 operation code, int64 request id, payload | `TcpClientChannel.java:387-394` |
| Cache key payload: int32 cache id = hash code of the name; flags 1/2/4; 3 x int64 expiry (flag 4); int32 tx id (flag 2); key then value | `ClientUtils.java:91-95`; `TcpClientCache.java:85-91, 1478-1509, 1439-1445`; server `ClientCacheRequest.java:35-68`, `ClientCacheDataRequest.java:40-44`, `ClientCacheKeyRequest.java:44-48`, `ClientCacheKeyValueRequest.java:34-38` (expiry before tx id on both sides) |
| Response: length; int64 request id (resource id for a notification); int16 flags (1.4.0+) 1/2/4; int64+int32 topology version (flag 2); int16 notification code (flag 4); int32 status (flag 1; always before 1.4.0); error message (when status not 0); payload | client read `TcpClientChannel.java:530-583`; server `ClientResponse.java:74-102`, `ClientFlag.java:48-55`, `ClientNotification.java:81-95`, `ClientAffinityTopologyVersion.java:63-68` |
| "first exchange", "matched by request id" | t3.p10, c3.p13 |

**d4-client-modules**

| Label | Source |
|---|---|
| Ignition.startClient -> TcpIgniteClient | `Ignition.java:584-588` |
| TcpIgniteClient facade: caches, SQL, transactions, compute, services | `IgniteClient.java` methods (query, transactions, compute, services, cache) |
| TcpClientCache handle per cache name | t4.p3 |
| ClientBinaryMarshaller, Ignite binary format | `TcpIgniteClient.java:143`, `ClientUtils.java:540-542` |
| ReliableChannel holders, default channel, retries, partition awareness | t4.p5 |
| ClientRetryPolicy (default ClientRetryAllPolicy) | `ClientConfiguration.java:148` |
| ClientCacheAffinityContext partition to node map; ClientDiscoveryContext server endpoints | `ReliableChannel.java:142-148` |
| ClientChannelHolder one endpoint list, reconnect throttling; "1..n" holders, "0..1" channel per holder | `ReliableChannel.java:69, 1005-1049` (`channels` list; holder field `ch` may be null) |
| TcpClientChannel one TCP connection: handshake, request ids, pending futures | t4.p7 |
| GridNioClientConnectionMultiplexer: GridNioServer in client mode, one selector | t4.p8 |
| GridNioClientParser 4-byte length framing | `ClientMessageDecoder.java:54-91` |

**d5-server-modules**

| Label | Source |
|---|---|
| ClientListenerProcessor binds the first free port 10800..10900 | `ClientListenerProcessor.java:160, 180-211` (inclusive `port <= portTo`, portTo = port + range) with defaults (c2.p12) |
| GridNioServer client-listener, selector threads | t5.p2 |
| GridNioSslFilter (only if sslEnabled) | `ClientListenerProcessor.java:410-432` |
| GridNioCodecFilter + ClientListenerNioMessageParser: length framing, first-message check | `ClientListenerProcessor.java:408`; `ClientMessage.java:146-211` |
| GridNioAsyncNotifyFilter -> client-connector pool, unbounded queue | t3.p12, t5.p4 |
| ClientListenerNioListener handshake, decode, respond | t5.p5, `ClientListenerNioListener.java:243-263` |
| ClientConnectionContext version, features, security, resources, transactions | `ClientConnectionContext.java:95-132`; security context in `ClientListenerAbstractConnectionContext.java:50-51` |
| ClientMessageParser op code to request class | t2.p6 |
| ClientRequestHandler process or processAsync | t5.p8 |
| Request classes e.g. ClientCachePutRequest -> IgniteCache (keep binary for key requests) (review fix K04) | t7.p9, t5.p11 (query requests with a Java filter use the raw cache) |
| ClientResponse header + payload -> "encode, session send" | `ClientListenerNioListener.java:257`, `ClientMessageParser.java:741-753` |

**d6-connect-handshake**

| Message | Source |
|---|---|
| Ignition.startClient(cfg) | c1/t1.p12 |
| new ReliableChannel (starts the client NIO server) | `TcpIgniteClient.java:151`; `ReliableChannel.java:150-151` |
| channelsInit() | t6.p2 |
| getEndpoints(): configured addresses; no port = 10800..10900 | t6.p3, c2.p17 |
| default holder: random among holders with the lowest port | `ReliableChannel.java:712-723` (only when no previous default holder) |
| getOrCreateChannel() / new TcpClientChannel | `ReliableChannel.java:1062-1079` |
| open socket (connect timeout = client timeout), SSL handshake if on | t6.p6 |
| note onConnected: handshake timer (10 s by default) | t6.p7, `ClientConnectorConfiguration.java:53` |
| handshake: version 1.7.0, type 2, features, attributes, credentials | c3.p5 |
| prepareContext, permissions, version check | t6.p8 |
| initializeFromHandshake: keep known features, authenticate | c3.p6, t6.p9 |
| accepted: true, features, node id / refused: false, server version or 0.0.0, message, status (review fix K15) | t6.p11 |
| retry with the server version (if the client supports it) | c3.p8 |
| GET_IDLE_TIMEOUT (only if heartbeats on and negotiated) | t6.p12 |
| add topology listener; nodeChannels[node id] = holder | t6.p13 |
| initAllChannelsAsync() (partition awareness on) | t6.p14 |
| GET_BINARY_CONFIGURATION (auto binary configuration + feature) | t6.p16 |
| first response on the connection (heartbeats off): flag 2 + topology version | t6.p17; "(heartbeats off)" because of open question c6.p6-p7 |
| topology listener: onTopologyChanged; refresh endpoints; channelsInit (in the background) | t6.p18 |

**d7-put-get**

| Message | Source |
|---|---|
| participant "ClientListenerNioListener (client-connector thread)" | t3.p12 / t5.p4 (onMessage runs in the pool worker) |
| put(key, val); affinityService(cacheId, key, CACHE_PUT 1001) | t7.p2, t7.p4; `ClientOperation.java:43` (1001) |
| choose channel: the key's node, or one the reliable channel picks (review fix K01) | c3.p18, t8.p17a (`ReliableChannel.java:815-852`) |
| service(op, writer, reader); send: next request id, pendingReqs.put(id, future) | `TcpClientChannel.java:319-327`, t7.p6 |
| length, op code, request id, cache id, flags, key, value | d3 rows |
| decode(msg) -> ClientCachePutRequest | t7.p7 |
| handle(req) in the security context | `ClientListenerNioListener.java:218-220` |
| process (atomic cache) or processAsync (transactional cache) | t5.p10, t5.p8 |
| put(key, val) on IgniteCache (keep binary); ClientResponse(request id) | t7.p9, t5.p11 |
| request id, flags [topology version] [status, message] | t7.p12, d3 rows |
| processNextMessage: match id, complete the future (selector thread) | t7.p13 |
| null for a put | `TcpClientCache.java:190-195` (reader null) and `TcpClientChannel.java:426-428` |
| get(key); CACHE_GET 1000 | t7.p14; `ClientOperation.java:46` |
| decode and handle as above: ClientCacheGetRequest.process; get(key) | t7.p15 |
| ClientObjectResponse: header + value | `ClientObjectResponse.java:41-45` |
| value read by the marshaller (binary if keep binary) | t7.p17 |
| value, or null if absent | server `cache.get` returns null for a missing key and `writeObject(null)` is read back as null; the test asserts it (`coretest/internal/client/thin/FunctionalTest.java:298`, `assertNull(cache.get(key))`) |

**d8-routing-failover**

| Message | Source |
|---|---|
| affinityService(cacheId, key, ...); affinityUpdateRequired(cacheId)? | c3.p18, t8.p2 |
| alt: no current mapping for the cache (missing, or older than the last topology) (review fix K05) | t8.p3 |
| CACHE_PARTITIONS 1101 (one thread at a time; others go without the map) (review fix K01) | t8.p3; `ClientOperation.java:136` |
| per node: primary partitions; only PARTITIONED + rendezvous caches | t8.p4, t8.p5 |
| readPartitionsUpdateResponse | `ReliableChannel.java:456` |
| affinityNode(cacheId, key); binary key -> partition -> primary node id (or none) | t8.p6, t8.p7 |
| service via nodeChannels[node id] | t8.p10 |
| onChannelFailure: close channel, fail listeners, roll the default | t8.p13 |
| shouldRetry? (system ops: always) | t8.p11, t8.p15 |
| participant "Fallback channel (see the note)" (review fix K01, was "Default channel (next holders)") | `ReliableChannel.java:835-852` |
| applyOnDefaultChannel; loop until success, attempts used up, or the policy says no (synchronous call) | `ReliableChannel.java:827-889`; the async path asks no policy for connect failures (t8.p21a), hence "synchronous call" |
| ClientConnectionException; onChannelFailure, next holder; no channel open and all attempts failed: reset discovery, channelsInit | t8.p13, t8.p19 |
| throw the first failure, the others suppressed | t8.p20 |
| participant "ClientRetryPolicy (default: retry all)" | c2.p20 |
| note: first try a random open channel if partition awareness is on and more than one channel is open, otherwise the current default holder, which moves on when it fails (review fix K01); attempts = holders, or retryLimit if smaller and above 0; one more with partition awareness and more than one open channel | `ReliableChannel.java:835-852` (choice), `rollCurrentChannel` 494-515 (moves on only when the failed holder is the default), t8.p17, t8.p17a |

## Actions (rule 15)

| Phrase | Command | Checked in this version |
|---|---|---|
| c2.p3 | `./mvnw clean install -Pall-java,licenses -DskipTests` | DEVNOTES.txt:17; profiles `all-java` (pom.xml:74) and `licenses` (pom.xml:260, parent/pom.xml:1133) exist |
| c2.p5 | `./mvnw -pl modules/core test -DFORK_COUNT_SET_TO_1 -Dtest='FunctionalTest#testPutGet*'` | profile parent/pom.xml:889-903; test method FunctionalTest.java:276; star for parameterized names (AbstractBinaryArraysTest @RunWith(Parameterized)); `-pl modules/core` is the module path in pom.xml:42; surefire 3.1.2 (parent/pom.xml:109) supports method filters (Surefire documentation, not run) |
| c2.p7 | `./mvnw initialize -Prelease`, unzip `target/bin/apache-ignite-2.17.0-bin.zip`, `bin/ignite.sh -v` (optional `-J-agentlib:jdwp=...`) | DEVNOTES.txt:28-32; ignite.sh `-v` and `-J<opt>` in parseargs.sh; default config ignite.sh:59-61 (row c2.p8, not spoken); log text ClientListenerProcessor.java:205 |
| c5.p1, c5.p8 | test command + `-Dmaven.surefire.debug`, attach to port 5005 | Surefire's documented debug property (not run); forked JVM required (FORK_COUNT_SET_TO_1); no `<debug>false` in any pom (grep), so classes have debug info |
| c5.p2 | ClientConfiguration.setLogger(new JavaLogger()), setEventListeners(connectionListener, requestListener) with two anonymous listener classes (review fix T13) | `JavaLogger()` public (JavaLogger.java:137); setters ClientConfiguration.java:885, 904; both listener interfaces have only default methods (ConnectionEventListener.java:27-48, RequestEventListener.java:27-41); accessors used: `throwable()` (HandshakeFailEvent 61, ConnectionClosedEvent 45, RequestFailEvent 67), `connectionDescription().remoteAddress()` (ConnectionEvent 35, ConnectionDescription 65), `operationName()`, `requestId()` (RequestEvent 62, 76); `new JavaLogger()` logs through the root java.util.logging logger (JavaLogger.java:137-139, 180) |
| c5.p10a | client logger; warnings Channel failure / Failed to update cache partitions mapping; debug lines | `ReliableChannel.java:462, 470, 536, 956, 972`; debug needs the root logger and console handler at FINE (JavaLogger with root logger) |
| c5.p4, c5.p9 | java.util.logging levels for `org.apache.ignite.internal.processors.odbc.ClientListenerNioListener` | JavaLogger debug = FINE, trace = FINEST (JavaLogger.java:336-343); logger name = class name (223-228); default file config/java.util.logging.properties (JavaLogger.java:102); JavaLogger is the fallback when log4j2 is absent (IgniteUtils.java:4834-4885) |
| c5.p10 | tests ThinClientPartitionAwarenessStableTopologyTest, ReliabilityTest | files exist in coretest; ReliabilityTest parameterized (partitionAware, async) |
| c5.p12 | `bin/control.sh --system-view client.connections --all-nodes` | SystemViewCommand registered (IgniteCommandRegistry.java:68), not @IgniteExperimental; `--all-nodes` from SystemViewCommandTest.java:148; default port 10800 (CommandHandler.java:140); SQL and Java view names accepted (SystemViewCommandArg.java:36-41) |

## Cross-check (rule 11)

First done after the walk JSON was written (136 phrases, 124 pointers, 2,633 words); after the review round:
validate PASS, 0 findings; 142 phrases, 131 code pointers, 8 diagrams, 11 actions, 2,679 spoken words.

- Claims from documents or inference, checked in code: c1.p3/p4 (README) are stated as the README's words; t1.p7
  stated as the discovery documentation's words; c2.p5, c3.p9, c3.p12, c3.p15, c3.p23, c3.p30, t5.p11, t6.p15,
  t8.p16, c6.p7, c6.p8 are inferences whose code paths are listed in their rows; c6.p7 and c6.p8 are spoken as open
  questions.
- Guarantees and their paths: "not retried" (c3.p9, c3.p15) - all ClientConnectionException catch sites in
  ReliableChannel (795, 865, 879, 924) and the async handler (275) were read; "always retried" for system ops (t8.p15)
  - shouldRetry is the only decision point, called at 290, 887, 930; "no client-side timeout" for async (c3.p16) - the
  only timed waits are in receive (424) and handshake (742); "never used" tcpNoDelay (c6.p1) - grep; "sends nothing"
  (t4.p3) - `cache(name)` and the TcpClientCache constructor read in full; "only one thread updates" (t8.p3) - the
  compareAndSet guard is the only entry to the update; "the connection stays open" on an unknown op code (former t5.p7, now not spoken) -
  ClientRawRequest is returned, no close in that path; "closes the session" on a parse failure (t5.p5 row) - 197.
- Diagram elements: every label has a row above; field orders in d3 were compared line by line with both writer and
  reader on each side; d3 members are forced to fields so PlantUML keeps their order.
- Decisive lines inside ranges: every pointer was printed with its range and checked by hand that the line named by the
  phrase (write, call, check, log text) is inside, including the end line; the anchor is taken from that line where
  possible.
- Corrected text re-checked (rule 17): during writing these were corrected and re-read against the code - d3 line
  order (PlantUML had moved lines with parentheses), d8 loop condition (added "or the policy says no") and the reset
  condition, d6 "first response" label (added "(heartbeats off)"), d7 get label (via parser and handler), t6.p12
  heartbeat interval (added the half-second floor and the cap; the phrase was later cut for length), c2.p1 (source
  level only, because of the java-15+ profile).
- Text rewritten while cutting the walk from 163 to 136 phrases, each re-read against its range in a full dump of all
  124 pointers: c1.p4 (four of the README's ten items), t1.p8 (drivers named, initialisms explained), c2.p5 (one
  phrase for the fork property), c3.p7 ("agreed features", source moved to the client read with the server side in
  limits), t4.p2 (constructor without the binary configuration step), t4.p12, t7.p10 (added "a quick check of
  partition awareness", backed by the metric descriptions), t8.p3 (merged with the former t8.p2), t8.p7 (added
  "primary", backed by the former t8.p5 row), t8.p21 ("same endpoint" instead of "same server": the reconnect goes
  through the same holder), c5.p5, c5.p6, c6.p8 (shorter, same claim); initialisms expanded at first use in c1.p4 (SQL), t1.p10
  (REST, HTTP), t1.p11 (TCP), t2.p2 (API), c6.p5 (to-do, fix-me) - same claims.

## Review round (2026-11-16): fixes after two independent reviews

Technical review T01-T13 and correctness review K01-K17 (the review reports are kept outside this repository). Each
finding was checked in the code first, then fixed. Every new or changed phrase, label and pointer was re-read against its range in a full dump
(rule 17); four of the new texts were corrected again during that re-read (t8.p16a "never agrees" instead of "retries
nothing", because system operations are retried without the policy; c5.p4a "the timer started at connect" instead of
"ten seconds later"; c2.p20 "agrees to every retry"; t6.p15 "each failure a warning"). Diagrams d3, d5, d6, d7, d8
were re-rendered and every diagramFocus text checked in the SVGs (validate: PASS, 0 findings).

## Not verified (rule 12)

- Nothing was built or run: no build, test, node start, debug session or log capture in this walk has been executed.
  The commands were checked against the build files and scripts only.
- Surefire behaviour assumed from its documentation, not from this tree: argLine applies only to forked JVMs,
  `-Dtest=Class#method*` patterns, `-Dmaven.surefire.debug` on port 5005.
- Runtime behaviour: timings, real failover against a stopped node, real partition-awareness hit rates, the open
  question (c6.p6-p7), the note on channelsInit (c6.p8), the late timeout warning after a refused handshake (c5.p4a), the
  async connect path that skips the policy (t8.p21a) and a timed-out put still being applied (c3.p15a) are readings of
  code, not observations.
- Not walked: the server's cache internals after `IgniteCache.put/get` (routing to the primary, backups, write
  synchronization, persistence), whether `ClientTxContext.close` rolls back, JDBC and ODBC paths, the C++ and .NET
  clients, SQL, compute, services, continuous queries, transactions beyond the "no failover" point, and the GridNioServer
  internals (threads, idle checks).
- Thread naming: the client selector's thread name format and the server pool thread names were not checked beyond
  the configured names ("thin-client-channel" server name, "client-connector" pool name).
- Which JDK the build needs at minimum was not established beyond the two Java profiles (11 to 14, 15 and later).

## Lead's corrections after the re-check (step E), 2026-11-16

| Phrase | Claim | Code |
|---|---|---|
| t6.p3a (new) | Holders of class ClientChannelHolder each keep a group of addresses (the channel configuration), the channel, and reconnect timestamps | ReliableChannel.java:1005-1019 |
| t6.p3b (new) | One holder is the default, connected first; at start picked at random among the holders with the lowest port | ReliableChannel.java:712-722 (dfltChannelIdx), 729-732 (curChIdx = dfltChannelIdx) |
| t8.p16a | Read / None policies limit resends; the one-time repeat can happen before any policy is asked | ClientRetryReadPolicy.java:23-49; ClientRetryNonePolicy.java:28-30; ReliableChannel.java:858-873 |
| t8.p21 | The repeat applies when a channel that was already open (c0 == c) turns out broken, with partition awareness on, in a synchronous call | ReliableChannel.java:858-873 |
| t8.p21b (new) | For the key's own node the policy is asked at once (shouldRetry(op, 0, e)); moves on only if it agrees and attemptsLimit > 1 | ReliableChannel.java:911-935 |
| c3.p28 | The client does offer atomic longs and sets | IgniteClient.java:231, 243, 254 |
| c6.p8 | Note, not a question: the endpoint branch runs only if no channel is open after the default one connected | ReliableChannel.java:759-769 |
| c5.p2 action | Snippet imports ClientConfiguration | org/apache/ignite/configuration/ClientConfiguration.java |
| c1.p1 | Length "about twenty-two minutes": 145 phrases, 2,798 words at 135 words a minute + 0.7 s gaps = 22.4 min | - |

## Grok review fixes (2026-11-16)

The rows below record the checked changes from the Grok 4.7 review (G01-G20); each finding was first checked in the
code. They give each
changed or new claim with its code lines; they supersede earlier rows for the same phrase or label (including the
c1.p1 row in the step E table and the "open question (c6.p6-p7)" wording in "Not verified"). Every row was re-read
against its range after the change (rule 17). Walk after the fixes: 156 phrases, 2,969 words, validate PASS.

| Phrase | Claim (spoken text) | Source | Exceptions and limits | How checked |
|---|---|---|---|---|
| c1.p1 | ... in about twenty-two minutes plus the stops. | inference (walk length) | 156 phrases, 2,969 words at the measured ~148 words a minute + 0.7 s gaps = 21.9 min; clips not re-measured | Counted in the final JSON |
| c3.p9 | A wrong password makes the handshake throw a client authentication exception. | code `TcpClientChannel.java:784-811` (785-786 AUTH_FAILED -> ClientAuthenticationException; 811 throw); server writes AUTH_FAILED on IgniteAccessControlException `ClientListenerNioListener.java:406-424` | A wrong user name gives the same status | Read the client failure branch and the server catch |
| c3.p9a | It is not a connection error, so the call tries no other server. | code `core/client/ClientAuthenticationException.java:23` (extends ClientException); `ReliableChannel.java:879-889` (only ClientConnectionException moves to another holder); not caught at `TcpClientChannel.java:226` or `ReliableChannel.java:924` either | The background connect task `ReliableChannel.java:569-575` logs any exception and goes on to the next holder; that is not the failing call | Read the catches and the class header |
| c3.p15 | If that timeout fires, the call fails with a plain client exception, and nothing tells the server to stop. | code `TcpClientChannel.java:434-441` (catch: log, convert, throw; nothing is sent) and `:515`; the timeout is `IgniteFutureTimeoutCheckedException` with no cause (`core/internal/util/future/GridFutureAdapter.java:247`, `core/internal/IgniteFutureTimeoutCheckedException.java:35-37`), so the checks at 490-512 all fail | Range 434-515 also contains receiveAsync (452-482) | Read receive, convertException, the end of GridFutureAdapter.get0 |
| c3.p15a | So a timed-out put may still be applied, and its late reply goes unused. | code `TcpClientChannel.java:585-592` (late reply removes and completes the pending future; the timeout path at 434-441 does not remove it) | "may still be applied": inference, the server processes independently; not observed | Read processNextMessage and receive |
| c3.p15b | The reliable channel retries only connection exceptions, so the call is not retried, and the connection stays open. | code `ReliableChannel.java:879-889` (only ClientConnectionException is caught; onChannelFailure, which closes the channel, runs only there); node path `:924-932` | | Read applyOnDefaultChannel and applyOnNodeChannelWithFallback |
| c3.p16 | An asynchronous call only registers a listener, so the wait for its response has no client-side timeout. | code `TcpClientChannel.java:452-481` (listen; get() without timeout after completion) | Connect and handshake still use the setting (c3.p16a-b); an async call that must open a channel does so synchronously (`ReliableChannel.java:245-250`, `:860`) | Read receiveAsync, handleServiceAsync |
| c3.p16a | The same timeout setting limits two more waits of every new channel: first, the socket connect. | code `GridNioClientConnectionMultiplexer.java:92` (connTimeout = cfg.getTimeout()), `:152` (connect with connTimeout); `open` is called per address from `TcpClientChannel.java:210` | Zero = no limit (`ClientConfiguration.java:60-61`); a failed connect is a ClientConnectionException (multiplexer 172) and the channel tries the holder's next address (`TcpClientChannel.java:215-220`) | Read constructor and open |
| c3.p16b | Second, the handshake reply. A handshake timeout is a connection error, so, unlike a request timeout, the call can move to another server. | code `TcpClientChannel.java:742` (same `timeout`, set at 200 from `ClientChannelConfiguration.java:126`), `:823-828` (IgniteCheckedException -> ClientConnectionException); constructor rethrows it `:226-228`; `ReliableChannel.java:879-889` moves on | "can": only while attempts remain and, for a synchronous public operation, if the policy agrees; the channel's other addresses are not tried after a handshake failure (226-228) | Read handshake, constructor, applyOnDefaultChannel |
| t4.p12 | When the client writes a binary type it has not registered yet, or whose metadata has changed, it first sends a separate put binary type request. | code `TcpIgniteClient.java:615-622`; `BinaryUtils.mergeMetadata` returns the old metadata when nothing changed (its javadoc) | Before channels exist (`ch == null`, 618) the request waits for `sendAllMeta` (634-640) | Read addMeta and mergeMetadata |
| t5.p14 | When a client disconnects, the server cleans up its resources. | code `ClientConnectionContext.java:247-251` (resReg.clean(), then super.onDisconnected()) | | Read |
| t5.p14a | It also closes the client's open transactions. | code `ClientListenerAbstractConnectionContext.java:133-134` (cleanupTxs), `ClientConnectionContext.java:325-330` (txCtx.close() for each) | Whether close rolls back: not verified (as before) | Read both |
| t7.p12 | The put answers with just a header: with flags in use and no error, the request id and flags, plus the topology version when the topology flag is set. | code `ClientResponse.java:82-94` (flags; version at 89-90; return at 93-94); `ClientAffinityTopologyVersion.java:63-67` (int64 + int32) | "flags in use" = partition-awareness feature (82) | Read both encode overloads |
| t8.p3 | If the cache's mapping is missing or older than the last topology, one thread at a time refetches it in its own call; others go without. With no last topology yet, nothing is fetched. | code `ReliableChannel.java:437-486` (443-444: no last topology -> false before any CACHE_PARTITIONS); `ClientCacheAffinityContext.java:121-131`, `:273-288` | "older" also covers no connected node of the last topology (`isTopologyOutdated` 318-331), as t8.p9 says | Read |
| t8.p7 | (text unchanged; range widened) | code `ClientCacheAffinityMapping.java:307-347` (nodeForKey 307-312 -> nodeForPartition 319-323 -> partMapping; mapper 344-345) | | Read |
| t8.p11 | In a synchronous call, if the node's channel fails, ... | code `ReliableChannel.java:924-935`, used only from the synchronous `service`/`affinityService` (210-216, 340-357); async affinity uses `applyOnNodeChannel` (398-409) and after a connect failure falls back to `serviceAsync` without the policy (795-804, 409) | Fix beyond Grok, same cause as G05 | Read |
| t8.p13 | The reliable channel catches only connection exceptions. | code `ReliableChannel.java:862-889` (both catches); node path 924; async 275-299 (other errors complete the future) | | Read |
| t8.p13a | For each, it logs channel failure, closes the channel, runs the fail listeners and, if its holder was the default, moves the default on. | code `ReliableChannel.java:536` (log), `538-539` (close if still the holder's), `541` (listeners), `544` with `494-515` (rolls only when the holder is the default) | | Read |
| t8.p16 | ... and is sent again on the next attempt, if one remains. | code `ClientRetryAllPolicy.java:28-29`; another send needs another attempt: `ReliableChannel.java:827` (sync loop), `:290` (async); one holder -> one attempt (`:947`) | The one synchronous repeat (`:866-873`, t8.p21) can resend even then; said in t8.p16b | Read |
| t8.p16a | To limit that, ClientRetryReadPolicy agrees only for reads. | code `ClientRetryReadPolicy.java:28-48` | | Read |
| t8.p16b | ClientRetryNonePolicy never agrees; one repeat, described shortly, can still happen before any policy is asked. | code `ClientRetryNonePolicy.java:28-29`; repeat `ReliableChannel.java:866-873` | System operations are retried without the policy (`:954-958`, t8.p15) | Read |
| t8.p19 | When the number of failures equals the number of attempts, not counting the extra one, and no channel is open, ... | code `ReliableChannel.java:546` (`F.size(failures) == attemptsLimit`); the extra attempt exists only in `fixedAttemptsLimit` (`:820-825`) | | Read |
| t8.p21b | A synchronous call to the key's own node is different: if that channel fails, the call fails without asking the policy when one attempt is the limit, and otherwise moves on only if the policy agrees. | code `ReliableChannel.java:924-935` (930: `attemptsLimit == 1` short-circuits before `shouldRetry`; 935 applyOnDefaultChannel) | Synchronous only (see t8.p11) | Read |
| c6.p1 | Some notes. The client's tcpNoDelay setting is copied into each channel's configuration, but never used. | code `ClientChannelConfiguration.java:125`; field `ClientConfiguration.java:58` (default true); `ClientChannelConfiguration.isTcpNoDelay` (170) has no caller (grep of all main sources) | JDBC thin and the server connector use their own settings (`JdbcThinTcpIo.java:224`, `ClientListenerProcessor.java:190`) | grep |
| c6.p1a | The client's network layer always turns TCP no-delay on. | code `GridNioClientConnectionMultiplexer.java:109` | | Read |
| c6.p2a | (text unchanged; re-pointed) | code `ClientListenerProcessor.java:175-178` (listener only when the limit is above 0); default 0 `ClientConnectorConfiguration.java:62`, `:127` | "only": the server write timeout (`GridNioServer.java:115`, `:2642-2649`) reaches `onSessionWriteTimeout`, a no-op (`GridNioServerListenerAdapter.java:27-29`), not overridden by ClientListenerNioListener; the filters pass it on (codec 146-148, SSL 470-472, async notify 133-135) | Read |
| c6.p2b | Once a session's outbound queue reaches that limit, the server closes the session and logs a warning. | code `ClientListenerProcessor.java:680-693` (warning after a successful close) | | Read |
| c6.p5 | The thin client's main sources carry no to-do or fix-me markers on either side; one test has a to-do. | grep TODO/FIXME: 0 in `core/client`, `core/internal/client/thin`, `core/internal/processors/platform/client`, kubernetes `org/apache/ignite/client`, and the top-level `processors/odbc` listener files; one in `coretest/internal/client/thin/ServiceAwarenessTest.java:391`; none in the core and indexing `org/apache/ignite/client` tests | The JDBC and ODBC request handlers under `processors/odbc` have two (not thin client) | grep |
| c6.p6 | Open question. With heartbeats on and supported by the server, the channel's constructor sets them up. | code `TcpClientChannel.java:253-255` | | Read |
| c6.p6a | That first asks the server for its idle timeout, and waits for the reply. | code `TcpClientChannel.java:925-942` (initHeartbeat -> getHeartbeatInterval -> synchronous service(GET_IDLE_TIMEOUT)); server answers with ClientLongResponse (`ClientGetIdleTimeoutRequest.java:37-38`) | | Read |
| c6.p7 | Only after the constructor returns does the reliable channel register as the channel's topology listener, so the topology flag the server puts on that first reply reaches no listener. | code `ReliableChannel.java:1079-1082`; first response flagged: `ClientLongResponse.java:41-42` -> `ClientResponse.java:109-110` -> `ClientConnectionContext.java:280-294` (no earlier version -> changed; t6.p17); client listener list still empty at `TcpClientChannel.java:539-546` (appended only at 638-639) | | Read the chain |
| c6.p7a | By the code, partition awareness then has no last topology, and fetches no partition map until a later response reports a newer topology version; this has not been tested. | code `ReliableChannel.java:443-444`; the last topology is set only by `updateLastTopologyVersion` (`ClientCacheAffinityContext.java:98-114`, called only from `ReliableChannel.java:590`; 237 resets it to null); a later flag needs a newer version (`ClientConnectionContext.java:285`) | Read from the code, not run | Read, grep |

Diagram labels changed (rendered again, every diagramFocus text checked in the SVGs by validate):

| Diagram | Label | Source |
|---|---|---|
| d7 | get reply: "request id, flags, [topology version], value" (was "request id, flags, value") | `ClientObjectResponse.java:41-44` -> `ClientResponse.java:82-94` |
| d8 | alt "no current mapping ..." now holds a nested alt: "[a last topology is known]" -> CACHE_PARTITIONS ...; "[no last topology yet]" -> "nothing fetched; the call goes without the map" | `ReliableChannel.java:441-444` |
| d8 | "[connection error on the node channel (synchronous call)]"; nested "[one attempt is the limit]" -> "throw the failure (the policy is not asked)"; "[more attempts allowed]" -> "shouldRetry? (system ops: always)", "applyOnDefaultChannel (only if the policy agrees)" | `ReliableChannel.java:924-935` |
| d8 | loop "[until success, attempts used up, or the policy says no]" ("synchronous call" moved to the outer alt) | `ReliableChannel.java:827-889` |
| d8 | "no channel open and failures = attempts (the extra attempt not counted): reset discovery, channelsInit" | `ReliableChannel.java:546-550`, `:820-825` |
| d8 | note: "first try: a random open channel if partition awareness is on, more than one channel is open and nothing has failed yet; otherwise the current default holder ..." (fix beyond Grok: on this diagram's path the node failure is already recorded, so the fallback starts at the default holder) | `ReliableChannel.java:838-852` (`F.size(failures) > 0` -> default holder) |

Not verified in this round: nothing was built or run. The open question (c6.p6-c6.p7a), the handshake-timeout failover
(c3.p16b) and a timed-out put being applied (c3.p15a) are readings of code. The connect timeout's behaviour with a value
of zero relies on `java.net.Socket.connect` semantics, not on this tree.

## Lead's check after the Grok fixes, 2026-11-16
- Checked in code: c3.p16a (GridNioClientConnectionMultiplexer.java:92 connTimeout = cfg.getTimeout(), :152 connect with it),
  c3.p16b (TcpClientChannel.java:742 fut.get(timeout), :828 ClientConnectionException), t8.p3, t8.p11, t8.p16, t8.p19, t8.p21b,
  t7.p12, c6.p5, c6.p6-c6.p7a against the lines they point at.
- t8.p21a reworded: "move on to another channel" instead of "move to the next holder" - the async call runs the same loop
  (ReliableChannel.java:245-250 -> applyOnDefaultChannel): first try a random open channel (partition awareness, >1 channel,
  no failure yet), after a failure the default holder (:838-852).
- t8.p21b removed before the repository integration: it repeated t8.p11 (the synchronous key's-node path, ReliableChannel.java:911-935).

## Lead's corrections after the Sonnet re-check of the Grok-round fixes, 2026-11-16
| Phrase | Claim | Code |
|---|---|---|
| c6.p2b | the warning is logged only when the close succeeds | ClientListenerProcessor.java:683 `if (fut.error() == null && fut.result())` |
| c6.p6 / c6.p7a | the "open question" label moved from c6.p6 (facts) to c6.p7a (the untested consequence) | - |
| c6.p7 | listener registered only after the constructor returns | ReliableChannel.java:1079-1082 |
| c6.p7b (new) | the first reply of a connection is marked changed: no last version yet | ClientConnectionContext.java:280-294 (`oldVer == null`) |
| TCP, SSL | already explained at first use (t1.p11, c2.p14); the re-check's remark not applied | - |
