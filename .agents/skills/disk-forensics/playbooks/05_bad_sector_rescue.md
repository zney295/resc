# Acquisition khi read error, reset hoặc disconnect

Không đồng nhất chậm 200 ms với bad sector, hoặc mọi USB flash lỗi với HDD head
crash. Ghi lỗi OS, timeout/short read, reset/capacity drift và source identity.

- Không scan metadata/signature sâu nhiều lần trên nguồn đang suy giảm. Chọn
  acquisition có budget hoặc chuyên gia hardware; No Media chưa có nguồn đọc.
- Trên Linux Live, dùng `scripts/rescue.py devices`, plan acquire rồi explicit
  --run; nguồn unmounted, ổ đích độc lập, geometry đúng. Fast/retry/resume/seal
  là GNU ddrescue CLI thật, xem [hướng dẫn](../../../../docs/two-computer-rescue.vi.md).
- Không bypass source/destination backing checks, không ghi map/ảnh lên nguồn.
  Không tự tăng retry vô hạn hay resume với device identity khác.
- Giữ rescue.map/source.json/image và sealed/received manifest. Ảnh PARTIAL có
  zero ở vùng unresolved; đó là unknown, không tự là bytes gốc.
- MCP DD_RESCUE_CLONE chỉ copy **ảnh** với per-sector fallback, không GNU ddrescue,
  không resume/multi-pass. Raw-device export/clone vẫn bị chặn.
- Poll dùng job_id, không session_id; terminal result cần kiểm riêng partial và
  unreadable bytes. Completed không có nghĩa mọi byte đọc thành công.
- Sau acquisition mở session ảnh bằng target_path/sector_size. Giữ RESC_SESSION_ROOT
  và không dùng phiên raw đang lỗi để quét lại nếu ảnh đã đủ.
- Cancellation/watchdog yêu cầu dừng I/O nhưng driver không đáp ứng vẫn có thể
  trì hoãn. Không hứa hard timeout hoặc reboot làm thiết bị lành.

[Reader controls](../../recovery-triage/references/reader-controls.md) và
[report](../../recovery-triage/references/report-and-handoff.md) xác định bằng
chứng còn thiếu khi kết quả ảnh giữa các reader không thống nhất.
