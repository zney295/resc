# Acquisition, zero-hit và định dạng ngoài phạm vi

## Chọn đúng nguồn/engine

Ảnh whole disk khác ảnh partition; mọi địa chỉ phải ghi byte hoặc LBA với geometry
512/4096. E01/VHDX/QCOW/VMDK không thành raw bằng đổi đuôi. Bộ .001/.002 phải đủ
segment theo định dạng; không mặc định .001 là ảnh đầy đủ. Conversion, RAID/dm/
Storage Spaces và decrypted views cần lưu mapping/provenance và engine phiên bản.

| Engine | Có gì | Giới hạn |
| --- | --- | --- |
| rescue.py trên Linux Live | Inventory/backing checks, external GNU ddrescue fast/retry/resume/seal | Source phải có capacity/geometry; cần ổ đích độc lập; không sửa firmware/NAND |
| rescue.py remote/pull | SSH key + strict host-key, staging acquisition và transfer hash/resume | Chưa direct remote block acquisition; cần healthy staging disk ở máy nguồn |
| MCP DD_RESCUE_CLONE | Copy image + map, sector fallback | Không GNU ddrescue, không resume/retry, raw-device clone/export bị chặn |
| evidence_audit.py | Audit/compare regular image files | Không acquisition/raw reader, không test persistence, không decode file |

Giữ map khi có unreadable/untried regions. Zero-fill chưa chắc bytes gốc. Hash
ảnh khớp chỉ xác nhận view đã chép; nếu ảnh partial, không gọi là whole acquisition.
Không tự nối hoặc xóa .part/manifest/map mà commit báo cần điều tra. Ưu tiên
snapshot immutable; overlay/WAL có thể làm view khác file gốc.

Xem [hướng dẫn hai máy](../../../../docs/two-computer-rescue.vi.md) cho lệnh CLI,
quyền đọc, dừng acquisition và resume binding. Chưa có helper Windows raw
acquisition trong repo này; ảnh chụp bản nâng cấp cục bộ ở máy khác không cài
helper đó vào checkout. Không bịa lệnh/path để gọi script chưa tồn tại.

## Zero-hit

Chỉ mở nhánh này sau terminal Completed, không phải trang đầu trống hoặc job
Cancelled/Failed. Trình tự:

1. Kiểm source đúng, sector size, volume/disk offsets và scan [start,end). Có đọc
   đủ range không, có budget/partial/unknown map không? Đọc hết pages hit bằng cursor.
2. Audit ảnh [bằng helper](audit-helper.md). Báo tỉ lệ 00/FF theo **bytes đã đọc**,
   sector runs bị cắt, full/partial; không suy tỷ lệ toàn USB từ một số mẫu.
3. Nếu reader khác nhau hoặc fill thống trị, làm [controls](reader-controls.md).
   Không thêm scan vô hạn hoặc vá boot bịa để tạo dữ liệu từ bytes không có.
4. Dùng metadata extents còn hợp lệ trước. Scanner hỗ trợ chữ ký hữu hạn, file
   có thể headerless, compressed/encrypted, nằm trong container hay format lạ.
5. Cần engine ngoài? Ghi tên/version, command dự kiến, output độc lập, source
   handling và expected evidence; kiểm nó đã cài/chạy chưa. Đừng gọi PhotoRec,
   TestDisk, TSK hay Untrunc là MCP integration đã bật.
6. Kết quả vẫn không có: báo 0 file, hypotheses và dữ liệu còn thiếu. Không kết
   luận overwrite/TRIM/NAND chết hay original payload chắc đã mất chỉ từ zero-hit.

## Metadata/format routes

- **NTFS/FAT allocated:** native tree dùng filesystem extents; format nội dung
  không giới hạn ở ảnh/video. Quotas và attributes unsupported vẫn áp dụng.
- **Deleted/format:** ghi quick/full format, lệnh/OS, overwrite/SSD discard context
  nếu biết. Không dùng quick/full như kết luận bytes còn/mất; đừng tái format để thử.
  FAT32 root SFN scan hẹp; NTFS deleted/journal native chưa triển khai.
- **JPEG/PNG:** marker/chunk CRC là structure, không pixel identity. Giữ ranh giới
  terminator và cạnh tranh candidate. Không tự tạo header rồi gắn nhãn original.
- **MP4/MOV:** box scan → candidate plan → bounded validator → export → FFmpeg;
  missing moov, unknown fragment order, full sample map/fMP4 cần thêm engine.
- **PDF/ZIP/OOXML/SQLite:** scanner có thể thấy header; native salvage/validator
  chuyên sâu chưa có. SQLite phải giữ WAL/SHM liên quan; thao tác engine ngoài
  trên bản sao, tránh mở/migrate database nguồn. ZIP cần CRC/member evidence;
  file Office có ZIP header chưa đủ xác nhận tài liệu nguyên vẹn.
- **exFAT/Ext4/APFS/RAID:** engine phù hợp trên bản sao; không ép NTFS/FAT parser,
  không copy backup superblock/RAID members theo offset cố định. Ngoài native.
- **BitLocker/FileVault/LUKS:** giữ encrypted acquisition và khóa hợp lệ nếu có;
  unlock view bản sao bằng công cụ phù hợp, ghi mapping. Entropy cao không tự
  chứng minh mã hóa và việc unlock không đồng nghĩa mọi file đọc được.

Kết thúc bằng [báo cáo](report-and-handoff.md), không dùng từ recovered cho mọi
signature, file đã copy hoặc bytes đo entropy.
