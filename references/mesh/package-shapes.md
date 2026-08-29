# Package shapes (MVP)

1. **Embedded.** Skill or project repo. OKF root at a folder such as `references/atlas`. Mesh `subpath` records that folder.
2. **Dedicated.** The repository is the Atlas. `subpath` empty, or a nested OKF root.

This skill’s canonical store is dedicated (`github.com/sergio-sisternes-epam/atlas-atlas`, OKF root `atlas/`) and is mounted into the skill as the `references/atlas` submodule. Compile/query root is `references/atlas/atlas`.

APM may copy files. Mesh membership still requires `atlas mount` of a git identity.
