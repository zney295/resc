---
name: disk-forensics-and-recovery
description: Điều tra USB/SSD/HDD/ảnh đĩa: No Media, lỗi quyền, reader không ổn định, nguồn 00/FF, mất phân vùng và acquisition trước recovery.
metadata:
  version: "3.0"
---

# Điều tra nguồn và bảo toàn dữ liệu

Bắt đầu bằng [recovery-triage](../recovery-triage/SKILL.md) và
[ma trận case](../recovery-triage/references/case-matrix.md). Nhiệm vụ đầu tiên là
xác minh có nguồn byte đáng tin, không mặc định mọi USB không nhận đều hỏng MBR.

## Phân tầng lỗi

- Không enumerate / Unknown USB Device: nhánh kết nối/driver/power, chưa có disk.
- No Media / 0 byte: chưa có addressable media; thu metadata, không ép scan.
- Access denied: quyền/chế độ mở khác với không có media; không đoán hardware lỗi.
- RAW/unallocated có dung lượng: acquisition rồi mới phân tích partition/boot.
- Read errors/reset/disconnect: acquisition có budget; không scan sâu nhiều lần.
- Hai reader khác nhau / ảnh gần toàn 00/FF: làm controls theo cùng offset/length
  và geometry. Cùng reader thay đổi qua lần đọc cũng chưa chỉ ra nguyên nhân.
- Dữ liệu mất sau reconnect / nghi dung lượng giả: chỉ đọc và giữ bằng chứng trước;
  [persistence lab](../recovery-triage/references/persistence-lab.md) là bước riêng.

Đọc [Windows/USB](../recovery-triage/references/windows-usb.md) hoặc
[reader controls](../recovery-triage/references/reader-controls.md) khi liên quan.
Helper audit chỉ nhận ảnh file thường; không dùng nó mở `D:` hoặc PhysicalDrive.

## Luật thực hành

Không ghi lên nguồn. Overlay không chặn OS hay tiến trình khác ghi. Không đổi
drive-letter/disk-number thành identity; ghi model, serial, capacity, sector size,
OS, reader version/flags và acquisition map. Mỗi địa chỉ phải có đơn vị byte/LBA
và geometry 512/4096. Không kết luận phần cứng đã chết chỉ vì lỗi IO/entropy thấp.

Chỉ dùng `tools/list` cho API. Native `DD_RESCUE_CLONE` chỉ clone ảnh, không resume/
retry đa lượt. Linux `scripts/rescue.py` gọi GNU ddrescue thật; raw-device
export/clone qua MCP vẫn NotImplemented. Nếu không có dữ liệu đọc được, chuyển
sang báo cáo giới hạn/handoff, không lặp quét vô hạn.

## Playbook hiện hành

- [MBR/GPT](playbooks/01_partition_recovery.md)
- [NTFS RAW](playbooks/02_ntfs_raw_repair.md)
- [FAT32/exFAT](playbooks/03_fat_exfat_repair.md)
- [Carving/phân mảnh](playbooks/04_defrag_carving.md)
- [Acquisition/lỗi đọc](playbooks/05_bad_sector_rescue.md)
- [Máy không boot/hai máy](playbooks/06_laptop_recovery_scenarios.md)

Báo riêng số bytes sao lưu, file được xác minh và độ ổn định sau reconnect theo
[mẫu báo cáo](../recovery-triage/references/report-and-handoff.md). Một USB đối
chứng chạy tốt không chứng minh backend với mọi USB thật đều đúng.
