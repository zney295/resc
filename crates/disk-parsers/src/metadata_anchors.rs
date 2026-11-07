//! Structural candidates on a raw volume view with no boot-sector dependency.
use serde::Serialize;

pub const MAX_ANCHOR_BYTES: usize = 8192;
const MAX_NTFS_INDEX_BYTES: usize = 4096;
const FAT_LAST_CLUSTER: u32 = 0x0fff_ffef;

#[derive(Serialize)]
pub struct FatDirectory {
    pub first_cluster: u32,
    pub parent_cluster: u32,
}

#[derive(Serialize)]
pub struct FatLayoutCandidate {
    pub data_start_lba: u64,
    pub sectors_per_cluster: u64,
    pub anchor_lbas: [u64; 2],
}

#[derive(Serialize)]
pub struct ExfatEntry {
    pub name: String,
    pub first_cluster: u32,
    pub data_length: u64,
    pub valid_data_length: u64,
    pub directory: bool,
    pub no_fat_chain: bool,
    pub entry_set_bytes: usize,
}

#[derive(Serialize)]
pub struct NtfsEntry {
    pub name: String,
    pub file_reference: u64,
    pub parent_reference: u64,
    pub file_size_hint: u64,
    pub index_vcn: u64,
    pub record_bytes: usize,
    pub entry_offset: usize,
}

fn u16_at(data: &[u8], start: usize) -> u16 {
    u16::from_le_bytes(data[start..start + 2].try_into().unwrap())
}

fn u32_at(data: &[u8], start: usize) -> u32 {
    u32::from_le_bytes(data[start..start + 4].try_into().unwrap())
}

fn u64_at(data: &[u8], start: usize) -> u64 {
    u64::from_le_bytes(data[start..start + 8].try_into().unwrap())
}

fn filename(units: &[u16]) -> Option<String> {
    let name = String::from_utf16(units).ok()?;
    (!name.is_empty() && !name.chars().any(char::is_control)).then_some(name)
}

pub fn fat_directory(data: &[u8]) -> Option<FatDirectory> {
    let dot = data.get(..32)?;
    let parent = data.get(32..64)?;
    if &dot[..11] != b".          " || &parent[..11] != b"..         " {
        return None;
    }
    for entry in [dot, parent] {
        if entry[11] != 0x10 || u32_at(entry, 28) != 0 {
            return None;
        }
    }
    let cluster =
        |entry: &[u8]| (u32::from(u16_at(entry, 20)) << 16) | u32::from(u16_at(entry, 26));
    let first_cluster = cluster(dot);
    let parent_cluster = cluster(parent);
    if !(2..=FAT_LAST_CLUSTER).contains(&first_cluster)
        || (parent_cluster != 0 && !(2..=FAT_LAST_CLUSTER).contains(&parent_cluster))
        || first_cluster == parent_cluster
    {
        return None;
    }
    Some(FatDirectory {
        first_cluster,
        parent_cluster,
    })
}

pub fn fat_layout(
    first: (u64, u32),
    second: (u64, u32),
    sector_size: usize,
) -> Option<FatLayoutCandidate> {
    let lba_delta = second.0.checked_sub(first.0)?;
    let cluster_delta = u64::from(second.1.checked_sub(first.1)?);
    if cluster_delta == 0 || !lba_delta.is_multiple_of(cluster_delta) {
        return None;
    }
    let sectors_per_cluster = lba_delta / cluster_delta;
    if !matches!(sector_size, 512 | 4096)
        || !sectors_per_cluster.is_power_of_two()
        || sectors_per_cluster > 65536 / sector_size as u64
    {
        return None;
    }
    let data_start_lba = first
        .0
        .checked_sub(u64::from(first.1.checked_sub(2)?) * sectors_per_cluster)?;
    Some(FatLayoutCandidate {
        data_start_lba,
        sectors_per_cluster,
        anchor_lbas: [first.0, second.0],
    })
}

pub fn exfat_entry(data: &[u8]) -> Option<ExfatEntry> {
    if *data.first()? != 0x85 || *data.get(32)? != 0xc0 || *data.get(64)? != 0xc1 {
        return None;
    }
    let secondaries = usize::from(data[1]);
    if secondaries < 2 {
        return None;
    }
    let set = data.get(..(secondaries + 1) * 32)?;
    let stream = &set[32..64];
    let name_length = usize::from(stream[3]);
    let name_entries = name_length.div_ceil(15);
    if name_entries == 0 || secondaries < 1 + name_entries || stream[1] & !3 != 0 {
        return None;
    }
    let checksum = set
        .iter()
        .enumerate()
        .filter(|(i, _)| !matches!(i, 2 | 3))
        .fold(0u16, |sum, (_, &byte)| {
            sum.rotate_right(1).wrapping_add(u16::from(byte))
        });
    if checksum != u16_at(set, 2) {
        return None;
    }
    let mut units = Vec::with_capacity(name_entries * 15);
    let name_end = 64 + name_entries * 32;
    for entry in set[64..name_end].as_chunks::<32>().0 {
        if entry[0] != 0xc1 {
            return None;
        }
        units.extend(
            entry[2..]
                .as_chunks::<2>()
                .0
                .iter()
                .copied()
                .map(u16::from_le_bytes),
        );
    }
    if units[name_length..].iter().any(|&unit| unit != 0)
        || set[name_end..]
            .as_chunks::<32>()
            .0
            .iter()
            .any(|entry| entry[0] & 0xe0 != 0xe0)
    {
        return None;
    }
    let first_cluster = u32_at(stream, 20);
    let data_length = u64_at(stream, 24);
    let valid_data_length = u64_at(stream, 8);
    let directory = set[4] & 0x10 != 0;
    if valid_data_length > data_length
        || (data_length == 0 && (first_cluster != 0 || directory))
        || (data_length != 0 && (!(2..=0xffff_fff6).contains(&first_cluster) || stream[1] & 1 == 0))
    {
        return None;
    }
    Some(ExfatEntry {
        name: filename(&units[..name_length])?,
        first_cluster,
        data_length,
        valid_data_length,
        directory,
        no_fat_chain: stream[1] & 2 != 0,
        entry_set_bytes: set.len(),
    })
}

pub fn ntfs_index(data: &[u8], sector_size: usize) -> Option<Vec<NtfsEntry>> {
    const INDEX_HEADER: usize = 24;
    if data.get(..4)? != b"INDX" || !matches!(sector_size, 512 | 4096) {
        return None;
    }
    let header = data.get(..40)?;
    let allocated = u32_at(header, 32) as usize;
    let record_size = INDEX_HEADER.checked_add(allocated)?;
    if record_size > MAX_NTFS_INDEX_BYTES
        || record_size < sector_size
        || !record_size.is_power_of_two()
    {
        return None;
    }
    let mut record = data.get(..record_size)?.to_vec();
    let start = INDEX_HEADER.checked_add(u32_at(header, 24) as usize)?;
    let end = INDEX_HEADER.checked_add(u32_at(header, 28) as usize)?;
    let usa = usize::from(u16_at(header, 4));
    let count = usize::from(u16_at(header, 6));
    // NTFS multi-sector transfer fixups use 512-byte strides.
    if count != record_size / 512 + 1
        || usa < 40
        || !usa.is_multiple_of(2)
        || usa + count * 2 > 510
        || usa + count * 2 > start
        || start > end
        || end > record_size
        || !start.is_multiple_of(8)
    {
        return None;
    }
    let sequence = u16_at(&record, usa);
    for i in 1..count {
        let trailer = i * 512 - 2;
        if u16_at(&record, trailer) != sequence {
            return None;
        }
        let original = u16_at(&record, usa + i * 2);
        record[trailer..trailer + 2].copy_from_slice(&original.to_le_bytes());
    }
    let mut entries = Vec::new();
    let mut offset = start;
    while offset < end {
        let entry = record.get(offset..end)?;
        if entry.len() < 16 {
            return None;
        }
        let length = usize::from(u16_at(entry, 8));
        let key_length = usize::from(u16_at(entry, 10));
        let flags = u16_at(entry, 12);
        let child_bytes = if flags & 1 != 0 { 8 } else { 0 };
        if flags & !3 != 0
            || !length.is_multiple_of(8)
            || length > entry.len()
            || 16 + key_length + child_bytes > length
        {
            return None;
        }
        if flags & 2 != 0 {
            return (key_length == 0 && length == 16 + child_bytes && offset + length == end)
                .then_some(entries);
        }
        let key = &entry[16..16 + key_length];
        if key.len() < 66 || key[65] > 3 || key.len() != 66 + usize::from(key[64]) * 2 {
            return None;
        }
        let units: Vec<_> = key[66..]
            .as_chunks::<2>()
            .0
            .iter()
            .copied()
            .map(u16::from_le_bytes)
            .collect();
        entries.push(NtfsEntry {
            name: filename(&units)?,
            file_reference: u64_at(entry, 0),
            parent_reference: u64_at(key, 0),
            file_size_hint: u64_at(key, 48),
            index_vcn: u64_at(header, 16),
            record_bytes: record_size,
            entry_offset: offset,
        });
        offset += length;
    }
    None
}
