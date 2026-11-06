# Bộ skill recovery v3: nhiều case, kiểm chứng trước khi sửa

Năm skill trong `.agents/skills/` dùng chung
[ma trận 17 case](../.agents/skills/recovery-triage/references/case-matrix.md).
Thay đổi này nâng hướng dẫn và helper audit ảnh; không bổ sung firmware repair,
Windows raw acquisition hay thuật toán tái dựng mọi mảnh file.

## Dùng với AI agent

Nếu nhận bản ZIP nâng cấp, giải nén vào thư mục riêng để xem diff trước. Giữ cấu
trúc `.agents/skills/`, `scripts/`, `docs/` và `ai-context/` cùng một repository
root; không chỉ copy mỗi SKILL.md vì các references/helper cần đi kèm. Sao lưu bộ
skill cục bộ đã chỉnh trước khi hợp nhất. Bản ZIP không có Rust binary, dữ liệu USB
của bạn hoặc helper Windows từ cuộc trò chuyện khác. Không tự cài vào máy cá nhân
từ cloud; người dùng/client phải chọn bộ skill ở vị trí thực sự đã giải nén.

1. Cho agent đọc [AGENTS.md](../AGENTS.md) và
   [recovery-triage/SKILL.md](../.agents/skills/recovery-triage/SKILL.md).
2. Nếu dùng MCP, build/chạy resc theo [hướng dẫn](recovery-guide.vi.md), gọi
   tools/list; không dùng lệnh cũ chỉ vì thấy trong chat/ảnh chụp báo cáo.
3. Bắt đầu từ triệu chứng/nguồn đang có, không ép chọn loại file. Router chỉ yêu
   cầu đọc references liên quan, rồi phân sang device/reader/acquisition/metadata/
   content hoặc báo cáo giới hạn.
4. Muốn audit/compare ảnh không cần MCP/Rust: helper stdlib Python >=3.11 chạy
   trên Windows/Linux với ảnh file thường. Không nhận raw device/volume handles.

## Những case đã thêm

- Không enumerate, No Media/0 byte, dung lượng chưa biết, sai quyền/path.
- Reset/disconnect/read errors và nhiều reader trả bytes không thống nhất.
- Ảnh 00/FF chiếm ưu thế, partial/zero-fill/untried regions và scan không ra hit.
- RAW/mất partition, deleted/format, file phân mảnh hoặc không biết loại file.
- Mã hóa/locked, filesystem/container/RAID chưa hỗ trợ native.
- Mất dữ liệu sau flush/eject/reconnect, nghi capacity alias, host không boot.
- Quota/no-space/cancellation/failed commit ở đích.

No Media không tự là lỗi NAND; scan không ra hit không chứng minh hết dữ liệu.
Hash ảnh chỉ xác nhận view đã đọc, không xác nhận những file trước kia trên USB.
Reader tests cần cùng offset/length/geometry/flags và nguồn đối chứng. Lab ghi/F3/
firmware không được tự chạy chỉ vì người dùng yêu cầu cứu dữ liệu hoặc nâng skill.

## Helper audit/compare

Thư mục `/results` dưới đây phải có sẵn trên ổ khỏe, report là tên mới:

```bash
python scripts/evidence_audit.py audit /evidence/usb.img --report /results/audit-001.json
python scripts/evidence_audit.py audit /evidence/usb.img --sector-size 4096 --max-bytes 16777216 --report /results/prefix-001.json
python scripts/evidence_audit.py compare /evidence/A.img /evidence/B.img --offset 1048576 --length 4096 --report /results/compare-001.json
```

Xem [giải thích field/exit codes](../.agents/skills/recovery-triage/references/audit-helper.md).
Đếm bytes/sector runs là exact trong phần đã đọc, ví dụ runs có giới hạn và báo
truncated. Budget/short read không được gắn hash toàn ảnh; sample equality không
được gắn whole-image equality. Helper không đọc lại USB, bỏ cache, chẩn đoán NAND,
test persistence hoặc xác minh định dạng file.

## Chỉ dẫn cũ đã sửa

Các playbook được thay để không gọi journal NotImplemented như đang có recovery;
không gọi native clone là ddrescue nhiều lượt; không dùng tham số MCP giả, copy
backup GPT header mù, mặc định mọi boot ở LBA 2048, FAT32 backup +6 hoặc Ext4 backup
ở block cố định. FSInfo 0xFFFFFFFF có thể hợp lệ; exFAT checksum không được coi
là chức năng native. Entropy không nhận diện ownership hay xác suất ghép đúng.

## Kiểm chứng và giới hạn

```bash
python tests/test_evidence_audit.py
python tests/test_recovery_skills.py
```

Bộ audit có 26 test trên ảnh tổng hợp: hash/counts, 4Kn, byte tail, offset trên
2 GiB, bounded examples, short reads/read errors/source identity drift, không
overwrite và không mở raw-device paths. Bộ skill có 3 contract checks: frontmatter,
links local và JSON tool examples theo catalog; đây không phải chứng nhận bởi một
validator bên ngoài. CI chạy hai bộ trên Ubuntu/Windows, với skip rõ cho semantics
symlink/rename không áp dụng hoặc không có quyền.

Ảnh chụp bạn cung cấp mô tả một cuộc điều tra USB và một bản skill/helper cục bộ
khác. Checkout này không có các helper/report/ảnh USB từ máy đó; chưa tái audit
USB 15,7 GB hoặc xác nhận lại các thống kê/test được chụp. Chưa sửa USB thật, chưa
phục hồi thêm file của người dùng và chưa test lưu bền sau reconnect bằng nâng cấp
này. Giữ **0 file recovered** nếu thực tế chưa xuất/kiểm chứng được file nào.

Kết quả chạy trong workspace: 26 audit tests + 3 skill contract checks đều đạt;
74 unit tests Rust, 16 nhóm E2E cũ và 27 integration tests recovery/acquisition cũ
cũng đạt. Format, Clippy -D warnings và release build đạt; cảnh báo future
compatibility của dependency khóa sẵn binrw 0.11.3 vẫn có. Chưa chạy Windows thật
hoặc kiểm thử USB vật lý; CI được cấu hình để chạy cả Ubuntu/Windows, không đồng
nghĩa kết quả CI từ xa đã được xác nhận ở đây.
