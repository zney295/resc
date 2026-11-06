# Windows/USB: xác định đúng tầng lỗi

## Thu quan sát chỉ đọc

Ghi OS, thời gian, cổng/hub/cáp, thiết bị là USB flash hay đầu đọc thẻ/enclosure,
model/serial, disk/volume identity, thông báo nguyên văn và dung lượng OS báo.
Nếu có bằng chứng sẵn thì dùng trước; không yêu cầu quét lại ổ lỗi chỉ để lấp mẫu.

Ví dụ PowerShell metadata dưới đây không format, initialize hay ghi payload:

```powershell
Get-CimInstance Win32_DiskDrive |
  Select-Object Index, DeviceID, Model, SerialNumber, InterfaceType, Size, Status, PNPDeviceID
Get-Disk |
  Select-Object Number, FriendlyName, SerialNumber, Size, BusType, OperationalStatus, HealthStatus, LogicalSectorSize, IsBoot, IsSystem
Get-Volume |
  Select-Object DriveLetter, FileSystem, HealthStatus, Size, SizeRemaining
Get-PnpDevice -PresentOnly |
  Where-Object { $_.Class -in @('USB', 'DiskDrive') } |
  Select-Object Class, FriendlyName, Status, InstanceId
```

Giữ cả lỗi quyền/cmdlet không có, không chuyển lỗi thành danh sách trống rồi báo
không có thiết bị. Get-Volume không thấy volume khác với Get-Disk không thấy disk.
PnP thấy controller hoặc đèn sáng không xác nhận có media hay sector đọc được.
Các lệnh WMI/storage cũng có thể bị driver treo; không có hard I/O timeout bảo đảm.
Đừng lặp cmdlet liên tục nếu thiết bị reset. Báo thiếu quan sát thay vì đoán.

## Quyết định

| Quan sát | Hành động | Điều kiện chuyển tiếp |
| --- | --- | --- |
| Không enumerate / Unknown USB Device | Một lần đổi cổng trực tiếp/bỏ hub hoặc đối chiếu máy khác nếu phù hợp; ghi kết quả | Có disk identity và capacity ổn định |
| No Media/0 byte | Không scan, vá boot hay ép capacity; phân biệt đầu đọc thẻ trống với USB flash lỗi; hardware handoff nếu dữ liệu quan trọng | Thiết bị thực sự cung cấp capacity và read path |
| Size null/unknown | Điều tra API/quyền/driver; không gộp null thành đo được 0 | Metadata độc lập có giá trị hoặc báo inconclusive |
| Access denied | Xác minh đúng device path, yêu cầu quyền đọc phù hợp; không lấy lỗi quyền làm bad sector | Mở nguồn read-only có geometry hợp lệ |
| RAW/Unallocated có capacity | Acquisition vào ổ khác; kiểm partition/boot trên ảnh | Ảnh/map giữ đủ phạm vi cần phân tích |
| Không có letter nhưng disk có capacity | Đối chiếu physical disk/partition; không tự gán letter hay mount nguồn | Có source identity, không chỉ tên D:/E: |
| Thay đổi bytes/size, disconnect, quá nóng | Ngừng scan sâu; acquisition chuyên biệt/handoff | Có nguồn byte ổn định hoặc ảnh partial có map |

MCP hiện lấy Win32_DiskDrive và trả tối đa 8 mẫu. Một thiết bị có thể không nằm
trong trang mẫu; trường recommendation cũ có thể chỉ dựa interface/removable,
không kiểm No Media. Không dùng `TARGET_EXTERNAL_DRIVE` làm bằng chứng đọc được.
Không gán máy đang chạy luôn là PhysicalDrive0 hoặc USB luôn là PhysicalDrive1.

## Giữ nguyên dữ liệu

Không dùng CHKDSK /f, diskpart clean, initialize, format, MPTool, firmware flash
hay secure erase để "thử cứu". Có thể thay đổi cơ hội recovery và không khắc phục
việc chưa có byte-source theo cách carver cần. Các bước ghi để tái sử dụng USB là
nhánh [lab riêng](persistence-lab.md), không được cấp quyền bởi yêu cầu nâng skill.

Đọc nguồn/chụp ảnh không sửa NAND/controller và read-only của resc không chặn OS
hoặc chương trình khác ghi. Với No Media dai dẳng sau đối chứng có giới hạn,
báo thiếu khả năng đọc sector; không cam kết phần mềm/chip-off chắc cứu được.

Tham khảo kỹ thuật: [Microsoft physical disks and volumes](https://learn.microsoft.com/en-us/windows/win32/fileio/physical-disks-and-volumes),
[Get-Disk](https://learn.microsoft.com/en-us/powershell/module/storage/get-disk),
[Get-PnpDevice](https://learn.microsoft.com/en-us/powershell/module/pnpdevice/get-pnpdevice).
