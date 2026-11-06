# Carving/phân mảnh: candidate không phải file đã cứu

Đọc [skill carving](../../file-carving-and-defrag/SKILL.md) và
[zero-hit](../../recovery-triage/references/acquisition-and-formats.md#zero-hit).
Không mặc định mọi file mất metadata chỉ có hai mảnh.

1. Acquisition có map và ảnh ổn định; kiểm coverage/fill/reader controls trước.
2. Signature discovery dùng job type/params thật. Ví dụ đối tượng tools/call
   dưới đây chạy trên ảnh; params rỗng là phạm vi mặc định, cần budget/range khi lớn:

```json
{"name":"start_async_disk_job","arguments":{"session_id":"ID_FROM_OPEN","job_type":"SIMD_MAGIC_CARVE","params":{}}}
```

3. Không truyền target_extensions/target_patterns (không có trong schema).
   Poll đến terminal, lấy hết hit pages. Header hit chưa xác định length/extents.
4. Giữ candidate plan theo logical order; không nhất thiết offset vật lý tăng.
   FRAGMENT_PREFILTER là heuristic, không biết codec semantics/ownership.
5. Validate JPEG/PNG/MP4/MOV bằng tool thích hợp. Format khác đi engine ngoài;
   unsupported không tự là file hỏng.
6. Export qua CARVE_BY_BYTE_RANGES với ranges, optional filename, output_dir mới.
   Poll DATA_EXTRACTION; lưu SHA-256/size/source mappings. Không dùng tham số
   output_filename/source_type/target_dir của ví dụ lịch sử.
7. Decode success không đủ xác nhận original. Nếu nhiều candidate pass, báo
   ambiguity và thiếu bằng chứng thay vì chọn mảnh có entropy tương tự.

Muốn tự tìm thứ tự mảnh chưa biết hoặc dựng moov mới cần thuật toán/fixtures
riêng; đó chưa phải chức năng được thêm bằng playbook.
