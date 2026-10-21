# Third-party notices

## Chatito

- Project: Chatito
- Upstream: https://github.com/rodrigopivi/Chatito
- Source revision: `8ad5d9835e1a0c7b95af7693cb58c0320ffc806f`
- Upstream package version at this revision: 2.4.0
- Copyright: Copyright (c) 2018 Rodrigo Pimentel
- License: MIT; the complete notice is preserved at `vendor/chatito/LICENSE`.

The source subset contains the CLI, its adapters and support modules, the parser
grammar, the generated parser, and the TypeScript configuration. It was copied
from the project's preserved Chatito snapshot. The original web application,
examples, tests and development environment are not bundled. Upstream source
files are unchanged. The minimal `package.json` and matching lock file were
prepared for this method package; they are not claimed to be upstream release
artifacts. `vendor/chatito/SOURCE_FILES.json` records bundled source hashes.

The generated parser is retained so installation does not need to regenerate it.
`ts-node` runs the original TypeScript CLI. Runtime dependencies are pinned in
`vendor/chatito/package-lock.json`; npm restores their own license files.
`node_modules` is not included in the distribution.

The MIT license in `vendor/chatito/LICENSE` applies to Chatito.
No license is specified for the telemetry template generator's original code.
