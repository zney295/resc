//! Read-only positional I/O. Windows requests are overlapped and cancellable.
//! CancelIoEx requests cancellation; buffers stay alive until kernel completion.
use crate::{AlignedBuffer, BadSectorMap, RawStorageReader};
use std::fs::File;
use std::io;
#[cfg(windows)]
use std::os::windows::io::{AsRawHandle, FromRawHandle};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};
use std::time::Duration;
#[cfg(windows)]
use std::time::Instant;
#[cfg(windows)]
use windows_sys::Win32::{
    Foundation::*,
    Storage::FileSystem::*,
    System::{Threading::*, IO::*},
};

pub const READ_TIMEOUT: Duration = Duration::from_millis(500);
pub struct PhysicalDrive {
    file: File,
    pub sector_size: u32,
    pub disk_size_bytes: u64,
    #[cfg(windows)]
    device_geometry: Option<DeviceGeometry>,
    bad: Mutex<BadSectorMap>,
}

#[cfg(windows)]
#[derive(serde::Serialize)]
struct DeviceGeometry {
    sector_size: u32,
    geometry_length_bytes: Option<u64>,
    length_info_bytes: Option<u64>,
    length_info_status: &'static str,
    length_info_error: Option<i32>,
}

#[cfg(windows)]
impl DeviceGeometry {
    fn capacity(&self) -> io::Result<u64> {
        self.length_info_bytes
            .or(self.geometry_length_bytes)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "Invalid device length"))
    }
}

impl PhysicalDrive {
    pub fn open(number: u32) -> io::Result<Self> {
        Self::open_path(&format!(r"\\.\PhysicalDrive{number}"))
    }
    #[cfg(windows)]
    pub fn open_path(path: &str) -> io::Result<Self> {
        let wide: Vec<u16> = path.encode_utf16().chain(Some(0)).collect();
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                std::ptr::null(),
                OPEN_EXISTING,
                FILE_FLAG_NO_BUFFERING | FILE_FLAG_OVERLAPPED,
                std::ptr::null_mut(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        let file = unsafe { File::from_raw_handle(handle as _) };
        let geometry = Self::geometry(&file)?;
        let mut drive = Self::from_file(file, geometry.sector_size, geometry.capacity()?)?;
        drive.device_geometry = Some(geometry);
        Ok(drive)
    }
    #[cfg(not(windows))]
    pub fn open_path(_: &str) -> io::Result<Self> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "NotImplemented: raw devices on this OS",
        ))
    }
    pub fn open_image(path: &str) -> io::Result<Self> {
        #[cfg(windows)]
        let file = {
            use std::os::windows::fs::OpenOptionsExt;
            std::fs::OpenOptions::new()
                .read(true)
                .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
                .custom_flags(FILE_FLAG_OVERLAPPED)
                .open(path)?
        };
        #[cfg(not(windows))]
        let file = File::open(path)?;
        let length = file.metadata()?.len();
        Self::from_file(file, 512, length)
    }
    fn from_file(file: File, sector_size: u32, length: u64) -> io::Result<Self> {
        if !matches!(sector_size, 512 | 4096)
            || length == 0
            || !length.is_multiple_of(sector_size as u64)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "Invalid disk geometry",
            ));
        }
        Ok(Self {
            file,
            sector_size,
            disk_size_bytes: length,
            #[cfg(windows)]
            device_geometry: None,
            bad: Mutex::new(BadSectorMap::new()),
        })
    }
    #[cfg(windows)]
    fn geometry(file: &File) -> io::Result<DeviceGeometry> {
        use windows_sys::Win32::System::Ioctl::{
            IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, IOCTL_DISK_GET_LENGTH_INFO,
        };
        let mut geometry = [0u8; 288];
        let size = Self::control(
            file,
            IOCTL_DISK_GET_DRIVE_GEOMETRY_EX,
            std::ptr::null(),
            0,
            &mut geometry,
        )?;
        if size < 32 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "Truncated disk geometry",
            ));
        }
        // DISK_GEOMETRY_EX contains the 24-byte DISK_GEOMETRY followed by DiskSize.
        let sector_size = u32::from_le_bytes(geometry[20..24].try_into().unwrap());
        let geometry_length = i64::from_le_bytes(geometry[24..32].try_into().unwrap());
        let mut buffer = [0u8; 8];
        let length = Self::control(
            file,
            IOCTL_DISK_GET_LENGTH_INFO,
            std::ptr::null(),
            0,
            &mut buffer,
        );
        let (length_info_bytes, length_info_status, length_info_error) = match length {
            Ok(8) if i64::from_le_bytes(buffer) > 0 => {
                (Some(u64::from_le_bytes(buffer)), "reported", None)
            }
            Ok(_) => (None, "invalid_response", None),
            Err(error) => (None, "unavailable", error.raw_os_error()),
        };
        Ok(DeviceGeometry {
            sector_size,
            geometry_length_bytes: (geometry_length > 0).then_some(geometry_length as u64),
            length_info_bytes,
            length_info_status,
            length_info_error,
        })
    }

    #[cfg(windows)]
    pub fn query_usb_storage_health(&self) -> io::Result<serde_json::Value> {
        use windows_sys::Win32::System::Ioctl::{
            PropertyStandardQuery, StorageDeviceProperty, IOCTL_DISK_IS_WRITABLE,
            IOCTL_STORAGE_QUERY_PROPERTY, STORAGE_PROPERTY_QUERY,
        };
        let geometry = self.device_geometry.as_ref().ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::Unsupported,
                "Storage diagnostics require a physical device",
            )
        })?;
        let query = STORAGE_PROPERTY_QUERY {
            PropertyId: StorageDeviceProperty,
            QueryType: PropertyStandardQuery,
            AdditionalParameters: [0],
        };
        let mut buffer = [0u8; 4096];
        let descriptor = Self::control(
            &self.file,
            IOCTL_STORAGE_QUERY_PROPERTY,
            std::ptr::from_ref(&query).cast(),
            std::mem::size_of_val(&query) as u32,
            &mut buffer,
        );
        let descriptor = match descriptor {
            Ok(size) => storage_descriptor(&buffer[..size]),
            Err(error) => {
                serde_json::json!({"win32_error": error.raw_os_error(), "status": error.kind().to_string()})
            }
        };
        let write_state = match Self::control(
            &self.file,
            IOCTL_DISK_IS_WRITABLE,
            std::ptr::null(),
            0,
            &mut [],
        ) {
            Ok(_) => serde_json::json!({"status": "writable"}),
            Err(error) if error.raw_os_error() == Some(ERROR_WRITE_PROTECT as i32) => {
                serde_json::json!({"status": "write_protected"})
            }
            Err(error) => {
                serde_json::json!({"status": "unknown", "win32_error": error.raw_os_error()})
            }
        };
        Ok(serde_json::json!({
            "geometry": geometry,
            "capacity_bytes": self.disk_size_bytes,
            "device_descriptor": descriptor,
            "windows_write_state": write_state,
            "scsi_pass_through": {"status": "unavailable", "reason": "Windows requires read/write handle access"},
            "limitations": ["Windows write state does not identify the protection layer", "Controller and NAND health are unverified"]
        }))
    }

    #[cfg(not(windows))]
    pub fn query_usb_storage_health(&self) -> io::Result<serde_json::Value> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "Storage diagnostics require Windows",
        ))
    }

    #[cfg(windows)]
    fn control(
        file: &File,
        code: u32,
        input: *const std::ffi::c_void,
        input_size: u32,
        output: &mut [u8],
    ) -> io::Result<usize> {
        let mut request = OverlappedRequest::new()?;
        let output_ptr = if output.is_empty() {
            std::ptr::null_mut()
        } else {
            output.as_mut_ptr().cast()
        };
        let success = unsafe {
            DeviceIoControl(
                file.as_raw_handle() as _,
                code,
                input,
                input_size,
                output_ptr,
                output.len() as u32,
                std::ptr::null_mut(),
                &mut request.request,
            )
        };
        let size = request.complete(file, success, None)? as usize;
        if size > output.len() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "Invalid device control response size",
            ));
        }
        Ok(size)
    }
    pub fn total_sectors(&self) -> u64 {
        self.disk_size_bytes / self.sector_size as u64
    }
    pub fn read_sectors_raw(&self, lba: u64, count: usize, buf: &mut [u8]) -> io::Result<()> {
        self.read_raw(lba, count, buf, None)
    }
    fn read_raw(
        &self,
        lba: u64,
        count: usize,
        buf: &mut [u8],
        cancel: Option<&AtomicBool>,
    ) -> io::Result<()> {
        let offset = lba
            .checked_mul(self.sector_size as u64)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "LBA overflow"))?;
        let size = count
            .checked_mul(self.sector_size as usize)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "Read size overflow"))?;
        if size > 1024 * 1024
            || size > buf.len()
            || offset
                .checked_add(size as u64)
                .is_none_or(|end| end > self.disk_size_bytes)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Physical read exceeds capacity/buffer/budget",
            ));
        }
        if cancel.is_some_and(|flag| flag.load(Ordering::Acquire)) {
            return Err(io::Error::new(io::ErrorKind::Interrupted, "Job cancelled"));
        }
        if size == 0 {
            return Ok(());
        }
        let mut aligned = AlignedBuffer::new(size)?;
        #[cfg(windows)]
        let result = self.overlapped(offset, &mut aligned[..size], cancel);
        #[cfg(unix)]
        let result = {
            use std::os::unix::fs::FileExt;
            self.file.read_exact_at(&mut aligned[..size], offset)
        };
        #[cfg(not(any(windows, unix)))]
        let result = Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "NotImplemented: positioned I/O",
        ));
        if let Err(error) = &result {
            if let Ok(mut map) = self.bad.lock() {
                let blocks = self.sector_size as u64 / 512;
                for block in lba * blocks..(lba + count as u64) * blocks {
                    if error.kind() == io::ErrorKind::Interrupted {
                        map.mark_slow(block, READ_TIMEOUT)
                    } else {
                        map.mark_bad(block, error.to_string())
                    }
                }
            }
        }
        result?;
        buf[..size].copy_from_slice(&aligned[..size]);
        Ok(())
    }
    #[cfg(windows)]
    fn overlapped(
        &self,
        offset: u64,
        buf: &mut [u8],
        cancel: Option<&AtomicBool>,
    ) -> io::Result<()> {
        let mut request = OverlappedRequest::new()?;
        request.request.Anonymous.Anonymous.Offset = offset as u32;
        request.request.Anonymous.Anonymous.OffsetHigh = (offset >> 32) as u32;
        let success = unsafe {
            ReadFile(
                self.file.as_raw_handle() as _,
                buf.as_mut_ptr(),
                buf.len() as u32,
                std::ptr::null_mut(),
                &mut request.request,
            )
        };
        if request.complete(&self.file, success, cancel)? as usize != buf.len() {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "Short overlapped read",
            ));
        }
        Ok(())
    }
}

#[cfg(windows)]
struct OverlappedRequest {
    request: OVERLAPPED,
    started: Instant,
}

#[cfg(windows)]
impl OverlappedRequest {
    fn new() -> io::Result<Self> {
        let event = unsafe { CreateEventW(std::ptr::null(), 1, 0, std::ptr::null()) };
        if event.is_null() {
            return Err(io::Error::last_os_error());
        }
        let mut request: OVERLAPPED = unsafe { std::mem::zeroed() };
        request.hEvent = event;
        Ok(Self {
            request,
            started: Instant::now(),
        })
    }

    fn complete(&self, file: &File, success: i32, cancel: Option<&AtomicBool>) -> io::Result<u32> {
        if success == 0 && unsafe { GetLastError() } != ERROR_IO_PENDING {
            return Err(io::Error::last_os_error());
        }
        let handle = file.as_raw_handle() as _;
        let request = &self.request;
        let mut transferred = 0;
        loop {
            let reason = if cancel.is_some_and(|flag| flag.load(Ordering::Acquire)) {
                Some(io::ErrorKind::Interrupted)
            } else if self.started.elapsed() >= READ_TIMEOUT {
                Some(io::ErrorKind::TimedOut)
            } else {
                None
            };
            if let Some(reason) = reason {
                unsafe { CancelIoEx(handle, request) };
                // Cancellation is asynchronous. Releasing the stack OVERLAPPED or
                // buffer before completion would be a use-after-free in the driver.
                unsafe { GetOverlappedResult(handle, request, &mut transferred, 1) };
                return Err(io::Error::new(
                    reason,
                    "Kernel read cancelled (driver completion drained)",
                ));
            }
            let wait = unsafe { WaitForSingleObject(request.hEvent, 10) };
            if wait == WAIT_OBJECT_0 {
                break;
            }
            if wait != WAIT_TIMEOUT {
                let error = io::Error::last_os_error();
                unsafe {
                    CancelIoEx(handle, request);
                    GetOverlappedResult(handle, request, &mut transferred, 1)
                };
                return Err(error);
            }
        }
        if unsafe { GetOverlappedResult(handle, request, &mut transferred, 0) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(transferred)
    }
}

#[cfg(windows)]
impl Drop for OverlappedRequest {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.request.hEvent) };
    }
}

#[cfg(windows)]
fn storage_descriptor(data: &[u8]) -> serde_json::Value {
    use serde_json::json;
    if data.len() < 36 {
        return json!({"status": "truncated"});
    }
    let field = |offset| u32::from_le_bytes(data[offset..offset + 4].try_into().unwrap());
    let declared = field(4) as usize;
    if declared < 36 || declared > data.len() {
        return json!({"status": "invalid_descriptor_size", "declared_bytes": declared});
    }
    let string = |offset| {
        let start = field(offset) as usize;
        if start < 36 || start >= declared {
            return None;
        }
        let bytes = &data[start..declared.min(start + 129)];
        let end = bytes.iter().position(|&b| b == 0)?;
        let value = std::str::from_utf8(&bytes[..end]).ok()?.trim();
        (!value.is_empty() && !value.chars().any(char::is_control)).then_some(value)
    };
    json!({"status": "ok", "bus_type": field(28), "removable_media": data[10] != 0,
        "vendor": string(12), "product": string(16), "revision": string(20)})
}
impl RawStorageReader for PhysicalDrive {
    fn len_bytes(&self) -> io::Result<u64> {
        Ok(self.disk_size_bytes)
    }
    fn read_physical_sectors(&mut self, lba: u64, count: usize, buf: &mut [u8]) -> io::Result<()> {
        self.read_cancellable(lba, count, buf, None)
    }
    fn read_cancellable(
        &mut self,
        lba: u64,
        count: usize,
        buf: &mut [u8],
        cancel: Option<&AtomicBool>,
    ) -> io::Result<()> {
        let offset = lba
            .checked_mul(512)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "LBA overflow"))?;
        let bytes = count
            .checked_mul(512)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "Read overflow"))?;
        if bytes > buf.len()
            || bytes > 1024 * 1024 - self.sector_size as usize
            || offset
                .checked_add(bytes as u64)
                .is_none_or(|end| end > self.disk_size_bytes)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Read outside source/buffer",
            ));
        }
        if bytes == 0 {
            return Ok(());
        }
        let sector = self.sector_size as u64;
        let prefix = (offset % sector) as usize;
        let blocks = (prefix + bytes).div_ceil(sector as usize);
        let mut aligned = AlignedBuffer::new(blocks * sector as usize)?;
        self.read_raw(offset / sector, blocks, &mut aligned, cancel)?;
        buf[..bytes].copy_from_slice(&aligned[prefix..prefix + bytes]);
        Ok(())
    }
    fn bad_sector_ranges(&self) -> Vec<(u64, u64)> {
        self.bad
            .lock()
            .map(|m| m.contiguous_bad_ranges())
            .unwrap_or_default()
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(windows)]
    #[test]
    fn pending_kernel_read_is_cancelled_for_timeout_and_job_signal() {
        use std::sync::Arc;
        use windows_sys::Win32::System::Pipes::*;
        for signal in [false, true] {
            let path = format!(
                r"\\.\pipe\resc-read-test-{}-{}",
                std::process::id(),
                u8::from(signal)
            );
            let wide: Vec<u16> = path.encode_utf16().chain(Some(0)).collect();
            let handle = unsafe {
                CreateNamedPipeW(
                    wide.as_ptr(),
                    PIPE_ACCESS_INBOUND | FILE_FLAG_OVERLAPPED,
                    PIPE_TYPE_BYTE | PIPE_WAIT,
                    1,
                    4096,
                    4096,
                    0,
                    std::ptr::null(),
                )
            };
            assert_ne!(
                handle,
                INVALID_HANDLE_VALUE,
                "{}",
                io::Error::last_os_error()
            );
            let file = unsafe { File::from_raw_handle(handle as _) };
            let client = std::fs::OpenOptions::new().write(true).open(&path).unwrap();
            // The client connected between CreateNamedPipe and ConnectNamedPipe.
            let connected = unsafe { ConnectNamedPipe(handle, std::ptr::null_mut()) };
            assert!(connected != 0 || unsafe { GetLastError() } == ERROR_PIPE_CONNECTED);
            let reader = PhysicalDrive::from_file(file, 512, 512).unwrap();
            let cancel = Arc::new(AtomicBool::new(false));
            let signal_thread = if signal {
                let cancel = cancel.clone();
                Some(std::thread::spawn(move || {
                    std::thread::sleep(Duration::from_millis(30));
                    cancel.store(true, Ordering::Release);
                }))
            } else {
                None
            };
            let start = Instant::now();
            let mut bytes = [0u8; 512];
            let error = reader
                .read_raw(0, 1, &mut bytes, Some(&cancel))
                .unwrap_err();
            assert_eq!(
                error.kind(),
                if signal {
                    io::ErrorKind::Interrupted
                } else {
                    io::ErrorKind::TimedOut
                }
            );
            assert!(start.elapsed() < Duration::from_secs(2));
            if !signal {
                assert_eq!(reader.bad.lock().unwrap().bad_count(), 1);
            }
            if let Some(thread) = signal_thread {
                thread.join().unwrap();
            }
            drop(client);
            drop(reader);
        }
    }
    #[test]
    fn image_reads_are_positional_and_observe_preexisting_cancellation() {
        let path = std::env::temp_dir().join(format!("resc-overlapped-{}.img", std::process::id()));
        std::fs::write(&path, vec![0x42; 4096]).unwrap();
        let mut reader = PhysicalDrive::open_image(path.to_str().unwrap()).unwrap();
        let mut bytes = [0; 512];
        reader.read_physical_sectors(2, 1, &mut bytes).unwrap();
        assert_eq!(bytes, [0x42; 512]);
        let cancelled = AtomicBool::new(true);
        assert_eq!(
            reader
                .read_cancellable(0, 1, &mut bytes, Some(&cancelled))
                .unwrap_err()
                .kind(),
            io::ErrorKind::Interrupted
        );
        drop(reader);
        std::fs::remove_file(path).unwrap();
    }
}
