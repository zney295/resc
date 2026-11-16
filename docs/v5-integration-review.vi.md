# Tích hợp có kiểm chứng từ bản Downloads v5

Đối chiếu ngày 2026-11-16 với `Downloads/resc_v5_0_complete/resc-v5.0`.
Nguồn được người dùng cho biết là bản Gemini Argon chỉnh sửa. Không coi mô tả
“69 tests”, “tương thích 100%” hay “hoàn tác 100%” là bằng chứng đã kiểm chứng.

## Phạm vi đã tích hợp

| Nhóm | Repo chính sau tích hợp | Giới hạn |
| --- | --- | --- |
| Header | `disk_header_inspector.py`: MBR, CRC GPT, BPB FAT, checksum exFAT, NTFS USA fixup, dấu hiệu ext, hex và dump ảnh | Đọc cấu trúc không chứng minh mount/decode; raw I/O Python là buffered, không có bảo đảm aligned-memory hoặc watchdog như Rust |
| Driver | `driver_and_device_manager.py inspect`: Windows disks, signed-driver INF/version/provider, services và filters; phân tích snapshot | Chỉ đọc; snapshot là user-reported; không suy NAND/FTL từ No Media, không xem filter khác mặc định là hỏng |
| Sửa thử/cứu file | `format_recovery_engine.py`: phân tích đề xuất, áp dụng patch plan vào WAL Rust, resume và trích xuất allocated NTFS/FAT | Không `--in-place`, không tự đoán VBR, không nhận hỗ trợ exFAT/deleted NTFS hoặc carving PDF/Office/SQLite |
| Không cần build | MCP Python riêng, một tool `inspect_disk_headers`; Node launcher fallback hoặc `RESC_BACKEND=python` | Không thay WAL/job/session Rust; công bố schema giới hạn. `recovery.py triage` thiếu binary trả header evidence và exit 2, không giả chạy scan |
| Cài đặt/CLI | `install.py`, `setup.ps1`, `resc_cli.py`, cài 5 skill và runtime scripts, wrapper `resc` | Không cần pip/npm; chưa thêm packaging Python/`pyproject.toml`. Wrapper/config trỏ repo, cần giữ repo tại chỗ; PATH không tự sửa |

Header inspector được dẫn xuất từ file cùng tên trong bản Downloads, SHA-256 nguồn:
`09a7d62b8ecbad411d1a4e172a99924e6c853ef8184600a8f3fe1b8cb1202013`.
Driver analyzer, MCP Python và adapter recovery được viết lại theo giới hạn của repo.
Các sửa đổi USB lab có sẵn trước phiên tích hợp được giữ lại, không thay bằng bản Downloads.

## Điểm mù đã xử lý

- Không nuốt lỗi I/O thành buffer rỗng rồi xem là boot trống. Dung lượng 0/không rõ bị từ chối.
- Kiểm tra độ dài header GPT, geometry và CRC array riêng; lấy backup ở cuối ảnh thay vì tin con trỏ primary hỏng.
- NTFS thực sự kiểm tra/thay USA trước đọc attributes; sector bị torn không được báo attributes hợp lệ.
- Giới hạn đọc 16 MiB/lần, đọc VBR trong biên phân vùng, kiểm tra FSInfo trailer và geometry exFAT.
- `0xEF53` chỉ xác nhận họ ext; partition FAT16 nhỏ trên ổ lớn không bị gắn nhãn giả chỉ vì dung lượng toàn ổ.
- Dump/report tạo độc quyền, không ghi đè. Dump raw device chưa hỗ trợ kiểm chứng ổ đích độc lập nên bị từ chối; acquire trước.
- Python MCP chỉ quảng bá tool đã hỗ trợ; JSON-RPC notification không có response, lỗi tool được báo `isError`, báo cáo dưới 5 KB.
- `doctor` phân biệt binary hiện diện với đã chạy kiểm chứng, và phân biệt Python diagnostics với native recovery.
- Cài script `.py` nguyên byte, không sửa Markdown link bên trong code; staging giữ đuôi `.cmd` để quyền suy ra trên Windows không làm sai readback.
- Preview cài đặt không build hoặc ghi file; apply có backup/readback/rollback của installer hiện hữu. Không ghi cấu hình người dùng thật trong test.

## Các phần không nhập nguyên bản

“WAL” Python của bản Downloads ghi đè JSON, binding chỉ dựa path/size/sector size;
không tương đương WAL CRC/fsync/locking của Rust. Không dùng nó để mở session Rust.

Đường `in-place`/rollback ghi thẳng nguồn vi phạm invariant của repo. Bản tổng hợp
VBR từ anchors có giả định geometry/partition end chưa đủ chứng cứ; chữ ký boot
mới không chứng minh file được phục hồi. Native overlay giữ vai trò thử sửa.

Driver repair có thể ảnh hưởng cả lớp thiết bị; reset/read-only removal/Registry
và pnputil update không được nhập dưới dạng hành động tự động. Việc nâng cấp phần
mềm không cho phép chạy các thao tác này trên máy hoặc USB người dùng.

Salvage bản Downloads có đường `write_bytes` ghi đè và các suy đoán contiguous
extents. Không nâng mức hỗ trợ exFAT/deleted/fragmented chỉ dựa trên fixture thuận lợi.
Giữ native extraction và manifest hiện có. USB format/canary tiếp tục dùng preview,
đúng identity, confirm token và data-loss acceptance của USB lab hiện hữu.

## Sử dụng

```powershell
python scripts/install.py --client both
python scripts/install.py --client both --apply
python scripts/resc_cli.py doctor
python scripts/resc_cli.py header inspect X:\evidence\image.img
python scripts/resc_cli.py driver inspect
python scripts/resc_cli.py format-recover reconstruct-format X:\evidence\image.img
```

`reconstruct-format` **chỉ phân tích đề xuất**. Để áp dụng thử, dùng
`format-recover apply-overlay IMAGE --partition-start-lba N --patch-plan PLAN.json`.
Plan chỉ chứa `patches` hoặc `copy_from_lba`/`to_lba`, tùy chọn `description`,
theo schema native `virtual_patch_and_verify`. Giữ `RESC_SESSION_ROOT` và session ID.
Kết quả `UNVERIFIED` giữ patch trong overlay và trả exit 2.

`format-recover salvage-files IMAGE --partition-start-lba N --resume-session-id ID
--output-dir OUTPUT` xuất file allocated qua overlay; không sửa ảnh nguồn.
Script cài trong skill dùng `--binary` hoặc `RESC_MCP_BIN` cho các lệnh cần native.
Chưa cài Rust vẫn dùng được header/driver/audit và MCP diagnostics giới hạn.

## Kiểm chứng

`python tests/test_upgrade_integration.py`: 16 tests tổng hợp, gồm CRC/geometry,
NTFS torn USA, lỗi đọc, FSInfo, output collision, JSON-RPC, cài đặt/idempotence,
CLI, fallback thiếu Rust và native overlay/resume/extraction giữ nguyên hash nguồn.

Hồi quy: 16 nhóm E2E; recovery workbench (6 passed, 1 skipped do thiếu FFmpeg);
recovery skills (7), USB verification (1), USB lab (5) đều qua.
Không thay Rust source nên không rebuild/re-run toàn bộ Rust workspace.
Chưa kiểm chứng USB thật, driver reset/update, raw device trên Linux hoặc decode video.
