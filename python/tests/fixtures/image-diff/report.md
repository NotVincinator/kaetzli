## What this build changes in the image — amd64

This build against run 41 (`aaaaaaa`) on `main`: 6 packages, 3 compiled-in modules, 11 paths, disk image +2.0 MiB.

### Packages

| package | before | after | in |
| --- | --- | --- | --- |
| `debug: strace` | 6.17 | — | −debug |
| `iproute2` | 6.17 | 6.17 | disk, −oci |
| `jq` | — | 1.8 | +disk, +oci |
| `k8s: kubelet` | — | 1.34 | +k8s |
| `openssl` | 3.5.3 | 3.5.4 | disk, oci |
| `podman: podman` | 5.6.0 | 5.7.0 | podman |

_in_: the disk image, the OCI image, or an extension; + where it is new, − where it is gone.

<details><summary>Go modules and Rust crates (3)</summary>

| package | module | before | after |
| --- | --- | --- | --- |
| `podman` | `github.com/gone` | 1 | — |
| `podman` | `github.com/new` | — | 2 |
| `podman` | `golang.org/x/sys` | 0.30.0 | 0.31.0 |

</details>

### Paths

| flavour | added | removed | renamed |
| --- | ---: | ---: | ---: |
| `erofs` | 5 | 4 | 1 |
| `oci` | 0 | 0 | 0 |

<details><summary>Paths in <code>erofs</code></summary>

```diff
+ usr/bin/jq
- usr/bin/routel
~ usr/lib/libssl.so.3.5.3 → usr/lib/libssl.so.3.5.4
+ usr/share/new/  (3 paths below)
- usr/share/old/  (2 paths below)
```

</details>

### Size

| | before | after | Δ |
| --- | ---: | ---: | ---: |
| `erofs` tree | 100.0 | 102.0 | +2.0 |
| `erofs` disk | 50.0 | 51.0 | +1.0 |
| `oci` tree | 50.0 | 50.0 | 0.0 |

MiB. The tree is apparent size, as `test/rootfs-size.py` measures it.

<details><summary>Where <code>erofs</code> changed</summary>

| directory | after | Δ |
| --- | ---: | ---: |
| `usr` | 82.0 | +2.0 |
| `usr/lib` | 22.0 | +2.0 |

</details>
