# Update and publish

```text
cd "$(python3 scripts/atlas.py resolve github.com/org/repo)"
git fetch
git pull
git commit
git push
```

There is no `atlas sync`. The mesh row `ref` is the branch `mount` recorded.
