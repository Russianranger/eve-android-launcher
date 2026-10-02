# Server runtime source and attribution

EVE.js 0.12.9 is licensed AGPL-3.0-only. Its original license, author attributions,
documentation and locked source files are installed at `/opt/evejs`; provenance
is in `/opt/evejs/UPSTREAM.json`. The upstream optional content packs are omitted.
The repository stores these sources as the numbered shards of
`vendor/evejs-source.tar.gz`, whose individual and concatenated checksums are
recorded by the directly committed upstream provenance file. CI
verifies and safely materializes that archive before compiling the runtime.
The Elysian v1 market seeder's attribution is retained in
`tools/market-seed/README.md`. This distribution contains no retail client files.

Node.js and its bundled dependencies retain their upstream licenses. SQLite is
public domain; better-sqlite3 and the npm dependencies retain their individual
LICENSE files inside `/opt/evejs/{server/,}node_modules`. Rust market dependencies
are listed in the upstream Cargo.lock files. Debian software retains copyright
and license information in `/usr/share/doc`.

Every published server runtime is accompanied by `server-runtime-source.tar.gz`
at the same GitHub release. It contains the EVE.js source, Android build scripts,
locked npm dependency source, Rust crate sources, the exact Node.js source archive,
and exact-version Debian source packages and license notices. See its
`SOURCE-INDEX.json` and `/usr/share/eve-android/debian-packages.tsv` for provenance.

Source and installation instructions are also available in the public repository:
https://github.com/Russianranger/eve-android-launcher
