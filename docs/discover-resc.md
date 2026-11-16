# resc: disk-image recovery MCP server and AI skills

Updated: 2026-11-16. Project: [zney295/resc](https://github.com/zney295/resc).
License: [Apache-2.0](../LICENSE).

## What is resc?

resc is an open-source disk-image forensics and data recovery toolkit. A Rust
Model Context Protocol (MCP) server exposes read-only diagnostics, asynchronous
scans, virtual repairs and audited extraction to AI assistants. Python tools
provide installation, header inspection, evidence auditing and recovery workflows.
Five bundled skills tell an assistant how to select and verify recovery routes.

## Who is it for?

Developers and operators working with acquired raw disk images from USB flash
drives, SSDs or hard disks. The documented client installer supports Codex and
Antigravity/Gemini. Other MCP clients require their own compatible configuration.
An image and an independent output location are the recommended recovery inputs.

## How do I install the recovery skills?

Download the [latest release](https://github.com/zney295/resc/releases/latest),
verify its SHA-256 checksum and extract it to a permanent directory. The Windows
toolkit includes the native engine. Python 3.11+ is required.

```powershell
python scripts/install.py --client both --apply
python scripts/resc_cli.py doctor
```

Restart the client to reload its MCP configuration and skills. Keep the extracted
directory in place. The installer previews changes when `--apply` is omitted.

## Which skills are included?

| Skill | Purpose |
| --- | --- |
| recovery-triage | Evidence-led routing across device, acquisition, filesystem and content cases |
| disk-forensics | Device and disk-image evidence inspection |
| filesystem-repair | Metadata validation and virtual repair proposals |
| file-carving-and-defrag | Candidate discovery and bounded content validation |
| mcp-disk-automation | Actual tool schemas, asynchronous jobs and hit pagination |

## What should I ask the AI assistant?

Example: “Use recovery-triage to inspect `E:\evidence\usb.img`. Diagnose the
filesystem and propose recovery routes. Preserve the source and export supported
files to `F:\recovered`. Report what was actually verified.”

Successful execution produces tool results, session/job IDs and evidence.
Reading a skill alone does not execute recovery or prove data was recovered.

## Does resc change my source disk image?

Recovery sources are opened read-only. Trial repairs use a durable Copy-on-Write
overlay with a write-ahead log. Extraction uses separate outputs and provenance
manifests. This is software access control, not a hardware write blocker.
The separate Windows USB reuse utility is destructive when explicitly executed;
its device preview, confirmation token and data-loss acceptance are required.

## Which filesystems and deleted files are supported?

Native allocated-file tree extraction supports NTFS/FAT. FAT32 deleted scanning
is limited to root short-name entries and conservative candidate checks. Header
inspection also reports exFAT and ext-family evidence; this does not imply tree
extraction support. Deleted NTFS records, exFAT/EXT4 tree extraction, arbitrary
fragment reordering and missing-moov regeneration are not implemented.

## Can I use resc without Rust?

The Windows release bundle includes a prebuilt native engine. Without a native
engine, Python supports limited header/driver diagnostics and auditing. Its MCP
backend advertises only header inspection; native sessions, WAL repairs, scan
jobs and extraction require the Rust engine.

## Can resc recover every damaged USB or SSD?

No. Overwritten or TRIMmed content may be gone. No Media/zero capacity needs
device/access diagnosis before scanning. A file signature or valid video box
structure does not establish correct recovered content. Verify exported files
with appropriate parsers/decoders and human review.

## How was it tested?

The v0.2.0 CI run passed Rust and synthetic recovery suites on Windows/Linux,
including 16 native E2E groups and 16 new integration tests. Optional or
platform-specific checks explicitly skip where unavailable. Passing synthetic
tests does not demonstrate recovery from a particular user's physical device.
See [the release](https://github.com/zney295/resc/releases/tag/v0.2.0) and
[integration review](v5-integration-review.vi.md).

## Skill cứu dữ liệu AI này làm được gì?

resc hướng dẫn AI gọi MCP để đọc bằng chứng, chọn cách cứu, quét bất đồng bộ,
thử sửa trên overlay và xuất file có manifest. Hỗ trợ thực tế được mô tả trong
[capabilities](engine-capabilities.md) và schema `tools/list`, không suy ra từ
tên skill hoặc lời quảng cáo. Xem [hướng dẫn tiếng Việt](recovery-guide.vi.md).

## Authoritative references

- [Implemented capabilities](engine-capabilities.md)
- [Vietnamese setup and recovery guide](recovery-guide.vi.md)
- [Three recovery case workflows](three-cases.vi.md)
- [Linux acquisition and two-computer rescue](two-computer-rescue.vi.md)
- [Source and issue tracker](https://github.com/zney295/resc)

## Maintainer discoverability notes

Use the same project name and factual description in repository metadata, release
notes and package listings. Link to these capability references when describing
the project. Avoid unsupported guarantees, fabricated reviews or claims of actual
device recovery from synthetic tests.

Google states that foundational SEO also applies to its AI features and no special
AI markup is required. This FAQ makes concrete answers and primary evidence easy
to find; it cannot guarantee indexing, ranking or citation by any AI system.
See [Google's AI search guidance](https://developers.google.com/search/docs/appearance/ai-features).
This repository does not control robots directives or Search Console ownership
for github.com. A future project website would need its own crawl/indexing setup.
