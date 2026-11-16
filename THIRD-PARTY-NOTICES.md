# Third-party notices

**MarketStore.** The walks in `walks/marketstore/` and `walks/marketstore-demo/` describe MarketStore version
4.1.23, copyright its authors (Alpaca and contributors), licensed under the Apache License, Version 2.0. The walks
contain file paths, line numbers and short identifying strings taken from that code, and diagrams that the author
of this repository drew from reading it, all at commit 007586568aa92a1c83189b3c06843dc27a23e5b3 (tag v4.1.23). No
source file of MarketStore is included here. `bootstrap.py demo` checks out that commit with git from a public copy
of the original repository (github.com/alpacahq/marketstore is no longer available): the unofficial GitHub copies
`FluxAstromeshLabs/marketstore`, `hickey/marketstore` and `nightsuns/marketstore`, or downloads version 4.1.23 as
the Go module `github.com/alpacahq/marketstore/v4` from the Go module mirror. The source tree is accepted only if it
matches the pinned checksum from the Go checksum database. A copy of the Apache License 2.0 is in `third_party/APACHE-2.0.txt`.
"MarketStore" and "Alpaca" are names of their owner and are used here only to say what the walks describe; this
project is not affiliated with or endorsed by Alpaca.

**Apache Ignite.** The walk in `walks/ignite-thin-client/` describes Apache Ignite 2.17.0, commit
`d53d4540b64bb4a25f1a5a1003c4338727628c9f` (tag `2.17.0`), licensed under the Apache License, Version 2.0.
It holds file paths, line numbers, short identifying anchors, and its author's own diagrams drawn from reading
that code. No Apache Ignite source file is included in this repository. `python3 bootstrap.py demo ignite`
gets exactly the pinned commit from `https://github.com/apache/ignite.git`, or GitHub's source archive if Git
is unavailable or the fetch fails, and verifies the same pinned tree checksum before use. The downloaded source
stays in the ignored `demo/` folder. A copy of the Apache License 2.0 is in `third_party/APACHE-2.0.txt`.

The pinned source's root `NOTICE` reads:

```text
Apache Ignite
Copyright 2023 The Apache Software Foundation

This product includes software developed at
The Apache Software Foundation (http://www.apache.org/).


This software includes code from IntelliJ IDEA Community Edition
Copyright (C) JetBrains s.r.o.
https://www.jetbrains.com/idea/
Licensed under Apache License, Version 2.0.
http://search.maven.org/#artifactdetails%7Corg.jetbrains%7Cannotations%7C13.0%7Cjar
```

Apache Ignite, Ignite and Apache are trademarks of The Apache Software Foundation. This project is not affiliated
with or endorsed by The Apache Software Foundation.

**PlantUML.** The diagrams were rendered with PlantUML. PlantUML is not included in this repository.

**Narration.** No narration audio is included. The player generates narration with your own Azure AI Speech key;
your use of that service is under your own agreement with Microsoft. If you publish audio made with it,
Microsoft's terms apply to you, including telling your audience that the voice is synthetic.
