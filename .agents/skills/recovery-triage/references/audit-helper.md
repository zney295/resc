# Helper audit/compare ảnh chỉ đọc

Chạy từ repository root, Python >=3.11, không cần pip hay Rust cho helper này.

```bash
python scripts/evidence_audit.py audit /evidence/disk.img --sector-size 512 --report /results/audit-001.json
python scripts/evidence_audit.py audit /evidence/disk.img --max-bytes 16777216 --run-limit 32 --report /results/prefix-001.json
python scripts/evidence_audit.py compare /evidence/reader-A.img /evidence/reader-B.img --offset 1048576 --length 4096 --report /results/compare-window-001.json
python scripts/evidence_audit.py compare /evidence/before.img /evidence/after.img --report /results/compare-full-001.json
```

Windows dùng cùng lệnh với đường dẫn ảnh thông thường trong dấu nháy, ví dụ
`"C:\\evidence\\usb.img"`; thư mục report trên ổ khỏe và tên phải mới. Không truyền
`D:`, `\\.\PhysicalDriveN`, volume handles, `/dev/sdX`, device nodes/symlink hoặc
reparse points. Helper không capture raw USB và không thay GNU ddrescue.

## Các field phải đọc

- `coverage`: offset, requested/read/compared bytes và whole-image flag. `--length`
  là phạm vi muốn audit; `--max-bytes` là budget có thể dừng sớm. Prefix/sample
  hoàn tất không có nghĩa đọc toàn ảnh. Partial/read-error/source-changed không pass.
- `sha256` chỉ có khi audit toàn ảnh không rỗng, đọc đủ và metadata không đổi.
  `read_range_sha256` chỉ mô tả bytes thực sự đã đọc. Có thể dùng
  `--expected-sha256 HASH_GOC_CUA_ANH` để kiểm độc lập; hash phải đến từ nguồn tin cậy.
- `byte_counts`: 00/FF/other theo bytes đã đọc; fill fraction không tính phần chưa
  đọc. `complete_sector_counts` không đếm partial sector thành sector hoàn chỉnh.
- `non_fill_sector_runs`: các LBA có **bytes đã quan sát** khác 00/FF, không phải
  file hoặc sector có dữ liệu người dùng. Một partial sector cũng có thể xuất hiện.
- `examples` bị giới hạn, mặc định 64 runs, tối đa 128; `omitted_runs`/`truncated`
  phải được giữ khi báo cáo. Đếm tổng là exact cho phạm vi đã đọc, ví dụ là bounded.
- `compared_range_equal` chỉ có kết luận khi đọc đủ window. `whole_images_equal`
  không được true cho sample/prefix. Khác length đã đủ bác bỏ ảnh bằng nhau;
  differing bytes chỉ đếm phần chung đã so, không gộp phần unmatched tail.
- `source_metadata_unchanged` kiểm handle/path identity, size và timestamps; không
  phải bảo đảm cryptographic rằng nguồn không bao giờ bị tiến trình khác sửa.

Chunk mặc định 1 MiB, tối đa 16 MiB; bộ nhớ không tăng theo kích thước ảnh. Audit
chunk phải là bội geometry 512/4096, offset audit phải sector-aligned. Compare hỗ
trợ cửa sổ byte bất kỳ, kể cả offset trên 2 GiB. EOF sớm và OSError được ghi READ_ERROR,
không lấp zero vào dữ liệu audit. Report JSON tạo exclusive, không ghi đè.

CLI stdout chỉ in summary nhỏ; chi tiết ở file report. Exit `0`: thao tác/window
hoàn tất (và so/hash nếu yêu cầu không lệch); `2`: partial/empty/mismatch hoặc
expected hash chưa xác minh; `1`: lỗi thao tác/read/source change. Exit 0 không
chứng minh USB đã sửa hoặc file original còn.

Helper không hiểu map acquisition để tự loại zero-fill; phải giữ map và đọc cùng
[báo cáo acquisition](acquisition-and-formats.md). Một ảnh audit tốt không kiểm
chứng reader USB, lưu bền sau reconnect, format nội dung hay NAND/controller.
