# Local Patch Layout

`test-k8s` can apply local `git format-patch` files to the checked out source trees before the workflows build or test them.

## Directories

- `projects/kubernetes/`: patches applied to the Kubernetes checkout
- `projects/containerd/`: patches applied to the containerd checkout

The patch directories may be missing or empty. CI treats both cases as a no-op.

## How To Create A Patch

Create the commit in the source repo first, then export it into the matching directory in this repo.

Kubernetes:

```bash
git -C /path/to/kubernetes format-patch -1 HEAD -o /path/to/test-k8s/projects/kubernetes
```

Containerd:

```bash
git -C /path/to/containerd format-patch -1 HEAD -o /path/to/test-k8s/projects/containerd
```

To export more than one commit, pass a commit range instead of `-1 HEAD`.

Example:

```bash
git -C /path/to/kubernetes format-patch HEAD~3..HEAD -o /path/to/test-k8s/projects/kubernetes
```

## Patch Order

Patches are applied in `LC_ALL=C` sorted filename order.

Use numeric prefixes to control the order:

- `0001-some-change.patch`
- `0002-follow-up.patch`
- `0010-later-change.patch`

If you need to renumber an existing series, rename the patch files in the target project directory before pushing.

## Notes

- Keep Kubernetes patches under `projects/kubernetes/` only.
- Keep containerd patches under `projects/containerd/` only.
- The workflows use `git am --3way`, so patches should be generated with `git format-patch`, not `git diff`.
