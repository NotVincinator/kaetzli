## Known vulnerabilities — amd64

grype 0.120.1, vulnerability database built 2026-11-01. Each CVE counted once per package and version. Reported, never enforced.

Open CVEs: what this build may be vulnerable to. **with a fix** means upstream has released one; **patched** counts those our patches already close, which are not in the other columns.

| SBOM | open | critical | high | medium | low | other | with a fix | patched |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `erofs` | 6 | 1 | 1 | 1 | 1 | 2 | 2 | 2 |
| `ext-podman` | 2 | 1 | 1 | 0 | 0 | 0 | 1 | 0 |
| `oci` | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 1 |
| **disk image + extensions** | 7 | 2 | 1 | 1 | 1 | 2 | 2 | 2 |

Most affected:

| package | version | CVEs |
| --- | --- | ---: |
| `kernel` | 7.3.1 | 3 |
| `golang.org/x/net` | v0.57.0 | 1 |
| `openssh` | 10.6p1 | 1 |
| `podman` | 5.7.0 | 1 |
| `tar` | 1.35 | 1 |

Patched by packages/*/patches (reported by grype, closed by VEX; not counted as open):

| CVE | severity | package | version |
| --- | --- | --- | --- |
| CVE-2026-7 | Unknown | `bash` | 5.3 |
| CVE-2026-6 | Medium | `glibc` | 2.44 |
