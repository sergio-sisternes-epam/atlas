# Atlas capabilities by git mode

| Capability | Remote git | Local git | Headless |
|------------|:----------:|:---------:|:--------:|
| compile / query | yes | yes | yes |
| edit in place | yes | yes | yes, no history |
| `atlas mount` / `atlas auth` | yes | mount yes, push no | no |
| commit | yes | yes | no |
| push / PR | yes | no until a remote exists | no |

Update a mounted store with git in the folder `atlas resolve <id>` prints.
