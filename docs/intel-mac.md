# Intel Mac builds

`intel-mac.yml` builds the app from `intel-mac`, merging the upstream stable
tag requested by `intel-mac-sync.yml`. The Intel app uses this fork's
`intel-feed` release for updates. Local dictation is unavailable on Intel;
its switch, microphone button and shortcut cannot start a recording or
download the speech model.

## Developer ID signing and notarization

In this fork's **Settings → Environments → apple-release**, add these secrets:

| Secret | Value |
| --- | --- |
| `MACOS_CERT_P12` | Base64 of a `.p12` export containing a valid **Developer ID Application** certificate and its private key. |
| `MACOS_CERT_PASSWORD` | The password used to export that `.p12`. |
| `AC_API_KEY_P8` | The complete PEM text of the App Store Connect API `.p8` key. |
| `AC_API_KEY_ID` | That API key's Key ID. |
| `AC_API_ISSUER_ID` | Its Issuer ID. |

The certificate requires Apple Developer Program access. An Apple Development
certificate or a public certificate without its private key cannot replace it.
Use GitHub's secret settings or `gh secret set --repo JulioAkaminee/zeron
--env apple-release NAME`; do not put the values in source files or logs.

The workflow imports the identity into a temporary keychain and checks notary
authentication before compiling. The existing macOS packaging script signs
the engine and app, submits the app and DMG to Apple, and staples the tickets.
The Intel workflow then checks Gatekeeper acceptance and both tickets before
publication. A final step restores the keychain list and deletes the temporary
keychain and API key, including after a failed build.

With none of the five secrets configured, automatic releases continue with
ad-hoc signing and release notes say so. A partial or invalid configuration
fails before compilation. `require_signing=true` also fails if the secrets
are absent; it never silently produces an ad-hoc build.

## Validate without replacing a published version

Run `intel mac` with `build_only=true` to run the Intel dictation checks and
produce a DMG, app tarball and checksums as workflow artifacts. This leaves
the releases and update feed untouched. Also set `require_signing=true` when
validating Apple credentials and notarization.

Only a run with `build_only=false` publishes to the release and feed. A
previously downloaded app does not gain these changes until a new build is
installed; preparing the workflow does not sign existing release assets.

Local workflow checks:

```sh
python3 scripts/tests/test_intel_macos_signing.py
actionlint .github/workflows/intel-mac.yml
```

The signing tests simulate macOS tools to cover credential checks and cleanup.
Actual Developer ID signing and Apple acceptance must pass on the Mac runner.
