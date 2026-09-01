# Releasing

Releases are cut by pushing a version tag. The [release
workflow](.github/workflows/release.yml) then builds the collection, publishes
it to [Ansible
Galaxy](https://galaxy.ansible.com/ui/repo/published/cfengine/cfengine/), and
attaches the tarball to a GitHub release.

## Prerequisites

- You must be an owner of the `cfengine` namespace on Ansible Galaxy.
- The `ANSIBLE_GALAXY_API_KEY` repository secret must hold a valid Galaxy API
  token. Galaxy tokens expire, so if a release fails while publishing, mint a
  fresh one at <https://galaxy.ansible.com/ui/token/> and update the secret.

## Cutting a release

1. Update `version` in `galaxy.yml`, following [semantic
   versioning](https://semver.org/)

2. Any module option added since the last release should carry a `version_added` matching
   the new version, so the Galaxy documentation shows when it became available:

   ```yaml
       edition:
           description: Edition of CFEngine that should be installed.
           version_added: "1.1.0"
   ```

3. Open a pull request with those changes and merge it to `master`.

4. Tag the merge commit and push the tag. Tags are bare semantic versions with no `v`
   prefix, annotated and signed:

   ```
   git checkout master
   git fetch upstream
   git rebase upstream/master
   git tag -s -m "Tag version 1.1.0" 1.1.0
   git push upstream 1.1.0
   ```

That last push is what triggers the release.

## Verifying

Watch the run under the repository's Actions tab. When it is green, check that:

- The tarball is attached to the [GitHub release](../../releases).
- The new version appears on Galaxy.

  ```
  ansible-galaxy collection install cfengine.cfengine
  ```

## Notes

- The workflow refuses to run if `version` in `galaxy.yml` does not match the tag. If it
  fails there, delete the tag, correct `galaxy.yml` on `master`, and tag again.
- **Galaxy does not allow re-uploading a version that already exists.** If a release is
  published and then found to be broken, it must be deleted from Galaxy or superseded by a
  new patch version — you cannot overwrite it.
- `build_ignore` in `galaxy.yml` keeps repository plumbing such as `.github` out of the
  published tarball. Anything added to the repository that should not ship to users needs
  an entry there.

## Building locally

To inspect the artifact without releasing anything:

```
ansible-galaxy collection build --output-path dist
tar tzf dist/cfengine-cfengine-*.tar.gz
```
