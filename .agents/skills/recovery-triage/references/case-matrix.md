# Ma trận case và điều kiện chuyển nhánh

Một ca có nhiều nhãn. Ưu tiên: khả năng truy cập → độ tin cậy reader → acquisition
→ filesystem/content → xác minh. Không bắt người dùng biết loại file mới làm được
triage. Các nhãn dưới đây là routing của **skill**, không thêm enum/tool MCP mới.

| Nhãn | Quan sát cần phân biệt | Việc tiếp theo | Không được suy ra |
| --- | --- | --- | --- |
| ENUMERATION_FAILED | Không thấy thiết bị / descriptor error | Windows/PnP, cổng/nguồn/cáp, thử đối chứng có giới hạn | Hỏng GPT; NAND chắc đã chết |
| NO_ADDRESSABLE_MEDIA | Disk báo No Media, capacity 0 hoặc chưa biết | Giữ metadata/lỗi; không scan hoặc patch | Thiết bị có sector vì có tên/VID/PID |
| ACCESS_PATH | Access denied, sai PhysicalDrive/volume letter | Đối chiếu quyền, identity, path và geometry | Mất dữ liệu hay lỗi phần cứng |
| UNSTABLE_IO | Timeout, reset, disconnect, size thay đổi | Dừng deep scan; acquisition/handoff có budget | Mọi lỗi đều bad NAND/HDD head crash |
| READER_DISAGREEMENT | Cùng địa chỉ/length cho bytes khác | Controls cùng reader, khác reader, nguồn chuẩn | Chọn reader có vẻ cho nhiều dữ liệu hơn là đúng |
| ZERO_FF_DOMINANT | Ảnh gần toàn 00/FF | Audit full/partial, map unknown regions, controls | TRIM, overwrite, chip chết, dữ liệu không bao giờ tồn tại |
| ZERO_SCAN_HITS | Scan hoàn tất nhưng không có candidate | Coverage, format support, reader và logical offsets | Không còn dữ liệu hoặc đã cứu xong |
| ACQUISITION_PARTIAL | Vùng lỗi/chưa đọc/ảnh bị cắt | Giữ map/prefix/identity; partial recovery có phạm vi | Zero-fill là byte gốc; hash ảnh chứng minh acquisition đủ |
| PARTITION_BOOT | Có capacity, MBR/GPT/VBR lỗi | So backup/proposal, overlay rồi validate/extract | Repair ảo làm USB dùng bền trở lại |
| DELETED_METADATA | Xóa nhầm/format, metadata không còn đầy đủ | Ghi loại format/OS; FAT32 root scan hoặc external undelete | Native tree extraction là undelete tổng quát |
| FRAGMENTS_CONTENT | Header/tail rời, file lỗi cấu trúc/nội dung | Known extents, validator, ambiguity, decoder | Entropy/độ gần chứng minh các mảnh cùng file |
| ENCRYPTED_OR_LOCKED | BitLocker/FileVault/LUKS hoặc dấu hiệu lock | Giữ ảnh mã hóa/key context; unlock bản sao bằng engine phù hợp | Entropy cao tự chứng minh mã hóa; AI phá khóa |
| UNSUPPORTED_LAYOUT | exFAT/Ext4/RAID/Storage Spaces/E01/segmented image | Nhận đúng container/layout, external read-only handoff | Đổi đuôi là raw; ghép RAID theo tên ổ |
| PERSISTENCE_UNVERIFIED | Copy/format có vẻ xong nhưng reconnect mất | Bảo toàn dữ liệu trước; protocol T0/T1/T2 trên media cho phép ghi | Flush/hash cùng phiên chứng minh dữ liệu lưu bền |
| CAPACITY_ALIAS_SUSPECTED | Ghi vùng cao ảnh hưởng vùng thấp / capacity đáng ngờ | Không tiếp tục ghi; lab/F3 chỉ sau bảo toàn và được phép | Model/serial/capacity báo cáo là dung lượng thật |
| HOST_UNBOOTABLE | OS hỏng hoặc máy không cấp nguồn | Live OS/SSH với staging hoặc tiếp cận SSD vật lý | Cáp USB thường làm máy tắt nguồn thành ổ đĩa |
| OUTPUT_OR_JOB_FAILURE | No space/quota/output exists/cancel/commit fail | Giữ file đã hoàn tất và recovery paths, sửa điều kiện đích | Tăng quyền lên nguồn hoặc scan lại sẽ sửa ổ đích đầy |

## Chọn tài liệu

- Device, No Media, quyền: [Windows/USB](windows-usb.md).
- Reader, 00/FF, đối chứng: [reader controls](reader-controls.md) và
  [audit helper](audit-helper.md).
- Partial, zero-hit, format/deleted/encryption/RAID: [acquisition/formats](acquisition-and-formats.md).
- Mất dữ liệu sau reconnect, capacity alias: [persistence lab](persistence-lab.md).
- Mọi nhánh kết thúc bằng [report/handoff](report-and-handoff.md).

Ví dụ: USB nhận 16 GB, ảnh chủ yếu 00/FF, hai reader chưa được đối chiếu và scan
không thấy file: gắn READER_DISAGREEMENT/ZERO_FF_DOMINANT/ZERO_SCAN_HITS theo bằng
chứng có thật; chưa gắn "NAND chết". Nếu thông tin chỉ là ảnh chụp báo cáo cũ,
ghi user_reported; chưa coi acquisition/hash là observed trên máy hiện tại.
