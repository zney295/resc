# SQLite: bảo toàn database/WAL, chưa có native page salvage

Scanner có thể phát hiện SQLite header; native orphan B-tree recovery/varint
salvage/schema reconstruction chưa triển khai. Một byte 0x0D tại boundary 4 KiB
không đủ xác nhận SQLite leaf page; page size và b-tree/overflow/schema semantics
cần engine chuyên biệt. Không có job SIMD_MAGIC_CARVE quét mọi 0x0D aligned page.

Giữ database và các WAL/SHM/journal liên quan nếu có. Không mở nguồn bằng engine
có thể tự checkpoint, migrate, truncate WAL hoặc ghi metadata. Làm forensic
snapshot, rồi dùng công cụ ngoài trên bản sao với version/config và source mapping
đã ghi. Orphan row extraction không tự là khôi phục toàn database/schema.

Nếu bytes trong ảnh fill thống trị, cần reader/coverage controls trước. File
SQLite được export qua known ranges chỉ xác nhận copy bytes, chưa integrity của DB.
Giữ derivative và lỗi, kiểm độc lập số row/table, integrity và nội dung quan trọng
trước khi báo recovered theo [report](../../recovery-triage/references/report-and-handoff.md).
