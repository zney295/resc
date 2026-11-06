---
name: recovery-triage
description: Phân loại nhiều tình huống cứu dữ liệu kể cả chưa biết loại file; kiểm chứng USB/reader, acquisition, ảnh 00/FF, zero-hit, persistence và recovery qua MCP theo bằng chứng.
metadata:
  version: "3.0"
---

# Recovery triage — kiểm chứng trước khi chọn cách cứu

Đọc [ma trận case](references/case-matrix.md) trước, sau đó chỉ đọc reference của
nhánh liên quan. Đọc [capabilities](../../../docs/engine-capabilities.md) và
`tools/list` trước khi điều phối MCP. Chạy script từ repository root; đường dẫn
trong ảnh chụp/log của người dùng không phải đường dẫn đang có trên máy này.

## Tiếp nhận ca

Ghi mục tiêu: lấy dữ liệu, làm thiết bị dùng lại, hay cả hai. Hỏi thông tin còn
thiếu ngắn gọn: OS/thông báo nguyên văn; dung lượng thực OS báo; nguồn/ảnh/map
đang có; thao tác trước sự cố (format, tháo bất ngờ, mã hóa). Không ép chọn JPEG,
video hoặc tài liệu nếu người dùng không biết. Nhiều case có thể cùng xuất hiện.
Không yêu cầu đủ mọi field mới làm bước chỉ đọc độc lập đã có đủ căn cứ.

Phân biệt `user_reported`, `observed`, `derived`, `not_tested`. Ảnh chụp một
báo cáo không xác nhận hash, reader, 15 GB đã đọc hay số test trên máy hiện tại.

## Thứ tự bắt buộc

1. **Thiết bị/đường truy cập:** phân biệt không enumerate, No Media/0 byte, lỗi
   quyền, volume RAW/không có drive letter và thiết bị mất kết nối.
   Đọc [USB/Windows](references/windows-usb.md). USB 0 byte chưa có sector để scan;
   nhãn `TARGET_EXTERNAL_DRIVE` của inventory cũ không chứng minh recoverability.
2. **Tin cậy đầu vào:** nếu reader không đồng ý hoặc 00/FF chiếm ưu thế, kiểm tra
   cùng identity, địa chỉ, độ dài, geometry, overlay revision và acquisition map.
   Dùng [reader controls](references/reader-controls.md); chưa biết reader đúng thì
   giữ nhiều giả thuyết. Không tăng số lượt quét trên nguồn lỗi để thay bằng chứng.
3. **Acquisition:** ưu tiên ảnh trên ổ đích độc lập, giữ source identity, map và
   vùng chưa đọc. [Acquisition/formats](references/acquisition-and-formats.md)
   phân biệt Linux ddrescue CLI, native image clone và các nguồn chưa hỗ trợ.
4. **Audit ảnh:** [helper chỉ đọc](references/audit-helper.md) tính hash/count
   00/FF và so hai ảnh theo cùng cửa sổ. Báo rõ full/partial, sample, lỗi đọc và
   phần bản đồ bị cắt. Hash trùng chỉ xác nhận bytes của ảnh/luồng được so.
5. **Recovery logic:** mở ảnh bằng `open_recovery_session(target_path, sector_size)`,
   rồi `diagnose_recovery`, `scan_disk_topology`. Chỉ dùng đề xuất backup đã kiểm
   geometry/identity trong overlay. `SUCCESS` xác nhận root traversal và file entry,
   không xác nhận mọi file hoặc thiết bị vật lý đã sửa.
6. **Tìm dữ liệu:** ưu tiên allocated extents NTFS/FAT. FAT32 deleted scan chỉ root
   SFN và candidate có giới hạn. Khi cần, scan signature/VBR/video trên ảnh với
   phạm vi và budget; [zero-hit](references/acquisition-and-formats.md#zero-hit)
   không đồng nghĩa không cứu được. Định dạng lạ/mã hóa phải có nhánh riêng.
7. **Content:** dùng `analyze_file_candidate`/`analyze_video_candidate` với byte
   plan có căn cứ. Giữ các candidate mâu thuẫn; structure/decode/hash/human review
   là các bằng chứng khác nhau. Không tự suy thứ tự mảnh bằng entropy.
8. **Xuất/kiểm chứng:** `extract_recovered_data` tạo job; poll đến terminal state,
   kiểm manifest, size, format/decoder và nội dung. Giữ output một phần, WAL/map/
   commit artifacts. Không quét lại nguồn chỉ vì trang hit đầu trống.
9. **USB dùng lại:** chỉ sau khi bảo toàn dữ liệu, đi nhánh
   [persistence/capacity lab](references/persistence-lab.md). Nâng cấp skill không
   cho phép tự ghi dữ liệu thử, format, flash firmware hay F3 lên USB của người dùng.
10. Báo [kết quả/handoff](references/report-and-handoff.md): số file thực sự lấy
    được; bytes chưa biết; điều đã/chưa kiểm chứng; bước tiếp theo và lý do dừng.

## Dừng đúng chỗ

- No Media, capacity thay đổi hoặc disconnect liên tục: không vá MBR/GPT, không
  tự mount/initialize/format, không kết luận NAND/controller chết từ một quan sát.
- Vùng zero do map chưa cứu được: giữ unknown, không gọi là TRIM/overwrite.
- Scan đã hoàn tất và zero-hit: audit coverage/reader/format trước khi đổi thuật toán.
- Không có file phục hồi: ghi **0 file**, không thay bằng số bytes đã sao lưu.
- Chưa đối chiếu ground truth thì chưa khẳng định original bytes; chưa kiểm T2
  sau reconnect thì chưa công bố persistence. Hai kết quả độc lập, không bắt buộc
  test ghi để xác nhận một file đã cứu. Không cam kết cứu mọi dữ liệu bằng skill.
- Máy không boot: [Linux Live/hai máy](../../../docs/two-computer-rescue.vi.md);
  SSH hiện cần healthy staging disk ở máy nguồn; bundle chưa phải boot ISO.

## Chọn skill chuyên sâu

- [disk-forensics](../disk-forensics/SKILL.md): bảo toàn nguồn, device/reader và boot.
- [filesystem-repair](../filesystem-repair/SKILL.md): proposal overlay NTFS/FAT,
  phân biệt exFAT/Ext4/RAID/encryption chưa hỗ trợ.
- [file-carving-and-defrag](../file-carving-and-defrag/SKILL.md): candidate/fragment/
  video, SQLite/ZIP ngoài phạm vi native.
- [mcp-disk-automation](../mcp-disk-automation/SKILL.md): async state, hit pagination,
  cancellation, quota và lưu bằng chứng.
