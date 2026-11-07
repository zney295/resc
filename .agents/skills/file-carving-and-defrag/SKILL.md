---
name: file-carving-and-defrag
description: Tìm và kiểm chứng candidate khi metadata/file type chưa rõ, zero-hit, JPEG/PNG/MP4/MOV và file phân mảnh; giữ ambiguity và phân biệt parser/decoder/nội dung.
metadata:
  version: "4.1"
---

# Carving và ghép extents có căn cứ

Đọc [triage](../recovery-triage/SKILL.md) và
[acquisition/formats](../recovery-triage/references/acquisition-and-formats.md).
Không biết tên/loại file vẫn bắt đầu được; không cần ép người dùng chọn video.

## Quy trình

1. Kiểm tra phạm vi acquisition, map unknown regions và
   [audit/compare](../recovery-triage/references/audit-helper.md) trước. 00/FF gần
   toàn ảnh hoặc các reader không đồng ý cần điều tra đầu vào trước đổi carver.
2. Trên ảnh ổn định, dùng metadata extents trước nếu còn. Discovery bằng
   `SIMD_MAGIC_CARVE`, `SIMD_VBR_HUNT` và `ISO_BMFF_BOX_SCAN` theo phạm vi/budget.
   Khi boot chính và dự phòng đều mất, `METADATA_WITHOUT_VBR` có thể tìm dấu vết thư mục.
   Mặc định scanner không đồng nghĩa mọi định dạng đều được nhận diện.
3. Lấy toàn bộ hit qua cursor. Hit là candidate header, chưa phải file hoàn chỉnh.
   Khi zero-hit, đi nhánh coverage/offset/format/encryption; không lặp cùng scan
   để coi số lượt chạy là bằng chứng mạnh hơn.
4. Giữ byte plan theo thứ tự logic, không chồng lấn, trong capacity. Physical
   order có thể ngược; mất metadata không chứng minh chỉ có hai mảnh.
5. `FRAGMENT_PREFILTER` là thống kê entropy/boundary để gợi ý, không nhận dạng
   ngữ nghĩa codec, không xác định cluster chưa cấp phát và không cho xác suất
   đúng. Nhiều candidate hợp cấu trúc phải được giữ riêng.
6. `analyze_file_candidate` hỗ trợ AUTO/JPEG/PNG/MP4/MOV. PNG CRC/JPEG markers
   không decode pixel. MP4 validator kiểm box/chunk starts, chưa mọi sample extent.
   Candidate terminator có thể ngắn hơn plan; trim theo logical order trước export.
7. Xuất qua `CARVE_BY_BYTE_RANGES`, poll DATA_EXTRACTION và kiểm manifest/hash/
   định dạng. FFmpeg decode chỉ kiểm decoder; video ghép sai vẫn có thể decode.
8. Không dựng bytes thiếu bằng AI rồi gắn nhãn nguồn gốc. Donor metadata/remux/
   statistical reconstruction (nếu dùng công cụ ngoài) phải thành derivative riêng.
9. PDF/ZIP/OOXML/SQLite có thể có hit nhưng native validator/salvage chưa có.
   Không dùng kết quả AUTO unsupported để kết luận file hỏng hoặc không có dữ liệu.

## Playbook

- [Heuristic prefilter](playbooks/01_boundary_coherence.md)
- [MP4/MOV](playbooks/02_mp4_mov_atom_repair.md)
- [SQLite/external salvage](playbooks/03_sqlite_database_salvage.md)
- [Bằng chứng và kết quả](../recovery-triage/references/report-and-handoff.md)
