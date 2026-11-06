---
name: mcp-disk-automation
description: Điều phối MCP recovery theo schema thật: async state, scan coverage, cancellation, hit pagination, WAL/quotas và báo partial/unsupported mà không giả lập thành công.
metadata:
  version: "3.0"
---

# Điều phối tác vụ và lưu bằng chứng

Đọc [triage](../recovery-triage/SKILL.md), capabilities và `tools/list`. Case
device/reader phải được phân loại trước khi gọi job. Không mở session 0 byte rồi
tự tăng timeout/retry để giả có addressable media.

- Chỉ truyền tham số có trong schema. Không dùng `target_extensions`,
  `target_patterns`, `retry_passes` cho native clone hoặc `scan_step_sectors`.
  External CLI và MCP có capability khác nhau.
- Mỗi lần chạy ghi source/session ID, sector size, overlay revision, job type,
  range [start_lba,end_lba), tool version, start/end và terminal state.
- `extract_recovered_data` trả DATA_EXTRACTION job. `start_async_disk_job` có các
  loại scan/native clone theo live schema. Không đợi file xuất đồng bộ trong reply.
- Poll vừa đủ để theo dõi, không busy-loop hoặc thông báo hoàn tất khi mới start.
  Hình trạng thái thật: `{"Running":{...}}`, `{"Completed":{"result":...}}`,
  `{"Failed":{"error":...}}` hoặc chuỗi `"Cancelled"`.
- Cancel: `poll_async_job(job_id, cancel=true)`, chờ terminal acknowledgement.
  Commit thành công chạy đua cancel có thể vẫn Completed với output.
- Trang đầu không đại diện mọi hit. `read_scan_hits` lấy `next_cursor` trả về,
  limit 1..100; response có thể ít hàng hơn do budget 5 KB.
- Không suy coverage từ tiến độ 100% nếu Failed/cancel/partial clone. Giữ unknown
  ranges, hit JSONL và [evidence report](../recovery-triage/references/report-and-handoff.md).
- At most 4 running jobs, 32 sessions/process; hit files chiếm đĩa và không tự có
  quota. Native tree: 10,000 files, 8 GiB, depth 64. Xem capabilities cho giới hạn
  WAL/patch; không bịa `overlay_memory_used_kb` hay tự clear/reopen để mất patch.
- Giữ `RESC_SESSION_ROOT`, source binding, WAL, output/map/manifest và commit
  recovery paths. Reopen image không resume live jobs; phải kiểm state cũ trước.
- Job đổi overlay revision có thể fail. Không chạy scan/patch mâu thuẫn đồng thời;
  poll/cancel dùng registry độc lập với overlay.
- Tool NotImplemented, timeout, missing dependency hay skip không phải recovery.
  Nếu zero-hit đọc [nhánh zero-hit](../recovery-triage/references/acquisition-and-formats.md#zero-hit).

[Playbook trạng thái/cursor](playbooks/01_async_job_orchestration.md) có ví dụ API.
