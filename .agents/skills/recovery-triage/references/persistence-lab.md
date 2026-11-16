# Persistence/capacity: lấy dữ liệu khác với sửa thiết bị dùng lại

Đây là **protocol lab** với CLI Pha B riêng cho USB Windows. Bắt
đầu bằng bảo toàn dữ liệu. Yêu cầu "nâng cấp skill" hoặc "cứu file" không tự cấp
quyền format, F3/MPTool hay ghi mẫu lên thiết bị cần cứu. Nếu chưa có quyền ghi
trên media xác định thì chỉ chuẩn bị kế hoạch và đọc các bằng chứng đã có.

## Trước lab có ghi

### CLI thực thi có xác nhận

Chạy preview `python scripts/usb_format_verify.py format --drive D: --filesystem exfat`.
Đối chiếu số disk, serial, UniqueId, dung lượng và volume với thiết bị người dùng
đã cho phép xóa. Sau xác nhận đó, chạy lại cùng lệnh kèm `--confirm TOKEN`
và `--data-loss-accepted`. CLI yêu cầu quyền Administrator, chặn Disk 0, C:,
Boot/System/Pagefile, ổ không phải USB và mọi trường hợp không xác minh được.
FAT32 giới hạn 32 GiB, MBR giới hạn 2 TiB trong lệnh này.

Lệnh format tạo MBR, một phân vùng rồi tự ghi bốn tệp mẫu 1 MiB. Có thể dùng
`python scripts/usb_format_verify.py write-canary --drive D:` để xem trước việc
ghi mẫu trên USB đã định dạng, sau đó thêm `--confirm TOKEN` khi được chấp thuận.
Mỗi tệp có dữ liệu ngẫu nhiên không chứa 00/FF, được flush và đọc lại đối chiếu
SHA-256. Manifest có bản trên USB và bản độc lập tại `%LOCALAPPDATA%/resc/usb-lab`.
Lỗi sau khi bắt đầu ghi để lại trạng thái FAILED_PARTIAL, không tự thử format lại.
T1 thành công trả `T1_VERIFIED_T2_PENDING`. Bốn tệp là bốn vùng logic, không
chứng minh bốn LBA vật lý hoặc toàn bộ dung lượng. Cần tháo an toàn, cắm lại và
đọc đối chiếu với manifest ngoài USB để xác minh T2.

Ghi chính xác device identity/serial/capacity, mục tiêu (recovery hay reuse), tình
trạng backup/hash/map, những gì chưa lấy được, ảnh nguồn bảo quản và output ổ
khác. Xác nhận thiết bị được phép mất nội dung và đúng đích lab; không mặc định
USB đối chứng là media có thể xóa. Không chạy thử nghiệm lên system/boot disk.

### Ba mốc quan sát

| Mốc | Thu gì | Không được gọi là |
| --- | --- | --- |
| T0: vừa ghi payload, trước flush/close | Pattern/file hash gốc trên ổ khỏe; path/offset/length; writer/API | Dữ liệu đã nằm bền trên NAND |
| T1: sau flush + close hoàn tất | Readback hash, bytes/metadata/file listing, lỗi flush | Đã vượt qua mất nguồn/reconnect |
| T2: sau safely eject và reconnect, re-identify | Cùng file/range hash + size, capacity/geometry, cache context, timestamps | Kiểm chứng mọi dung lượng hoặc mọi lần dùng tương lai |

Payload phải có nội dung biết trước, khác nhau giữa các vùng và lưu hash ngoài
USB. Có thể dùng pattern ngẫu nhiên với seed được ghi; chỉ toàn zero là đối chứng
yếu. Lặp cùng protocol trên media khỏe nếu đã cho phép, giữ conditions giống nhau.
Không rút nóng để ép lỗi và không tắt chế độ bảo vệ mà chưa có kế hoạch được phép.
Flush thành công không phải bảo đảm tuyệt đối thiết bị giữ dữ liệu sau mất nguồn.

## Ma trận phân biệt nguyên nhân

| Kết quả | Hướng điều tra | Bằng chứng còn cần |
| --- | --- | --- |
| Payload/range còn đúng, filesystem lỗi | Metadata/partition/driver path; dựng trên overlay và export kiểm hash | Identity/geometry, filesystem validation, user file checks |
| T0/T1 đúng nhưng T2 mất/đổi payload | Persistence path, cache, nguồn/bridge/controller/media | Reader controls, healthy control, repeat có budget; chưa chỉ ra component |
| Ghi vùng cao liên quan đổi vùng thấp | Capacity/address-alias hypothesis | Offsets/patterns riêng biệt, đối chứng; full-capacity test ngoài recovery |
| Sai trên ảnh chuẩn trước khi chạm USB | Backend offset/length/alignment/short-read bug | Regression tái lập; sửa code rồi chạy controls lại |
| Hai reader khác, mỗi bên tự ổn định | Cache/flags/chunking/addressing/view mismatch | Cùng source/range và payload chuẩn để biết bên đúng |

F3/H2testw/manufacturer tools là công cụ ngoài; bài test ghi có thể phá dữ liệu.
F3 ở đây chỉ là lựa chọn trong lab được phép sau backup, không có lệnh tự chạy,
không phải native MCP job. Không suy "USB sửa được" từ quick format hay copy một
file nhỏ. Một test qua trên phạm vi nhỏ chưa xác minh dung lượng quảng cáo.

## Tiêu chí kết thúc

- **Recovery:** file đã xuất, hash/size/format/content review có phạm vi; nếu không
  có bản gốc thì không khẳng định byte-identical original. Số file lấy được có thể 0.
- **Reuse/persistence:** payload chuẩn còn đúng sau T2 trên phạm vi đã thử, kèm
  coverage và lỗi. Nếu chưa chạy T2 thì ghi NOT_TESTED; không thay bằng unit tests.
- **Chưa rõ:** lưu observations/hypotheses, đề xuất bước phân biệt tiếp theo hoặc
  hardware handoff. Nếu nguyên nhân không thể xác định từ phần mềm, không hứa
  tiếp tục nâng skill đến khi chắc chắn sửa được thiết bị.

Tham khảo: [Microsoft file buffering](https://learn.microsoft.com/en-us/windows/win32/fileio/file-buffering),
[FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers),
[F3](https://github.com/AltraMayor/f3). Kiểm thử mô phỏng của CLI Pha B không
thay cho kết quả persistence đo trên USB cụ thể.
