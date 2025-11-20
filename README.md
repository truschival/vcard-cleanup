# VCard Cleaner v2.0

A comprehensive Python utility for cleaning, modernizing, and standardizing VCard (.vcf) files to the vCard 4.0 (RFC 6350) format with UTF-8 encoding and ISO 8601 date formatting.

## Features

- **vCard 4.0 Compliance**: Upgrades legacy vCard files to modern RFC 6350 standard
- **UTF-8 Encoding**: Enforces UTF-8 encoding (default in vCard 4.0)
- **ISO 8601 Dates**: Converts all timestamps to standardized ISO 8601 format
- **iOS Corruption Cleanup**: Removes problematic ITEM prefixes from iOS-exported VCards
- **Type Normalization**: Converts TYPE parameters to lowercase (vCard 4.0 style)
- **Photo Processing**: Automatically resizes large photos and removes duplicates
- **Address Cleaning**: Fixes malformed address fields and removes escape sequences
- **Contact Splitting**: Split multi-contact VCard files into individual contact files
- **RFC Compliance**: Generates proper UIDs and PRODID fields

## Installation

### Requirements

- Python 3.6 or higher
- PIL (Pillow) for photo processing (optional but recommended)

### Setup

1. Clone or download the repository
2. Install dependencies (optional but recommended for photo processing):

   ```bash
   pip install Pillow
   ```

## Usage

### Basic Usage

Clean a VCard file with auto-generated output filename:

```bash
python3 vcard_cleaner.py contacts.vcf
```

Specify custom output file:

```bash
python3 vcard_cleaner.py contacts.vcf cleaned_contacts.vcf
```

### Split Contacts

Split a multi-contact VCard file into individual files:

```bash
python3 vcard_cleaner.py --split contacts.vcf
```

Split with custom output directory:

```bash
python3 vcard_cleaner.py --split --output-dir ./individual_contacts contacts.vcf
```

### Command-Line Options

```text
usage: vcard_cleaner.py [-h] [--split] [--output-dir OUTPUT_DIR] [--version] input_file [output_file]

positional arguments:
  input_file            Input VCard file (.vcf) to clean
  output_file           Output VCard file (default: auto-generated based on input filename)

optional arguments:
  -h, --help            show this help message and exit
  --split               Split contacts into individual VCard files
  --output-dir OUTPUT_DIR
                        Output directory for split files (default: same as input file directory)
  --version             show program version number and exit
```

## Example

### Input VCard (Legacy/Corrupted)

```vcf
BEGIN:VCARD
VERSION:3.0
PRODID:-//Apple Inc.//iOS 16.0//EN
UID:12345678-1234-1234-1234-123456789012
FN:John Doe
N:Doe;John;;;
ITEM1.EMAIL;type=INTERNET;type=HOME:john.doe@example.com
ITEM2.TEL;type=CELL:+1-555-123-4567
ITEM3.ADR;type=HOME:;;123 Main Street\nApt 4B;Springfield;IL;62701;USA
ITEM4.URL;type=HOME:https://johndoe.example.com
PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRgABAQEAYABgAAD...
REV:2024-11-20 14:30:00
END:VCARD
```

### Output VCard (vCard 4.0 Cleaned)

```vcf
BEGIN:VCARD
VERSION:4.0
PRODID:-//VCard Cleaner v2.0//RFC 6350//EN
UID:a1b2c3d4-e5f6-7890-abcd-ef1234567890
FN:John Doe
N:Doe;John;;;
EMAIL;TYPE=home:john.doe@example.com
TEL;TYPE=cell:+1-555-123-4567
ADR;TYPE=home:;;123 Main Street, Apt 4B;Springfield;IL;62701;USA
URL;TYPE=home:https://johndoe.example.com
PHOTO:data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...
REV:2024-11-20T14:30:00Z
END:VCARD
```

### Key Improvements

1. **VERSION**: Upgraded from `3.0` to `4.0`
2. **PRODID**: Updated to RFC 6350 compliant identifier
3. **ITEM Prefixes**: Removed (`ITEM1.EMAIL` → `EMAIL`)
4. **TYPE Parameters**: Uppercase and normalized (`type=HOME` → `TYPE=home`)
5. **Address Formatting**: Cleaned escape sequences (`\n` removed)
6. **Photo Format**: vCard 4.0 data URI format (removed ENCODING parameter)
7. **Timestamps**: ISO 8601 format (`REV:2024-11-20T14:30:00Z`)
8. **UTF-8 Encoding**: Enforced (no CHARSET parameters needed)

## Type Normalization and Mappings

The cleaner standardizes and reduces the variety of TYPE parameters to a core set of vCard 4.0 compliant types. This ensures better compatibility across different contact applications.

### Phone (TEL) Type Mappings

The tool maps various phone types to a simplified set of standard types:

| Original Type | Mapped To | Description |
|---------------|-----------|-------------|
| `HOME` | `home` | Home phone number |
| `WORK` | `work` | Work/business phone number |
| `CELL`, `MOBILE`, `IPHONE` | `cell` | Mobile/cellular phone |
| `VOICE`, `MAIN` | `voice` | Voice calls (primary) |
| `TEXT`, `MSG` | `text` | Text messaging capable |
| `FAX` | `fax` | Fax number |
| `VIDEO` | `video` | Video calling capable |
| `TEXTPHONE` | `cell` | Text phone mapped to cell |
| `PAGER`, `BBS` | `text` | Paging services mapped to text |
| `PCS`, `CAR` | `cell` | Alternative mobile types |
| `MODEM`, `ISDN` | `voice` | Legacy connection types |

### Email (EMAIL) Type Mappings

| Original Type | Mapped To | Description |
|---------------|-----------|-------------|
| `HOME` | `home` | Personal email address |
| `WORK` | `work` | Work/business email |
| `PREF` | `pref` | Preferred email address |
| `INTERNET` | *removed* | Redundant in vCard 4.0 |
| `X400` | *removed* | Obsolete email system |

### Address (ADR) Type Mappings

| Original Type | Mapped To | Description |
|---------------|-----------|-------------|
| `HOME` | `home` | Home/residential address |
| `WORK` | `work` | Work/business address |
| `PREF` | `pref` | Preferred address |
| `DOM`, `INTL`, `POSTAL`, `PARCEL` | *removed* | Obsolete in vCard 4.0 |

### Benefits of Type Reduction

- **Compatibility**: Simplified types work across more applications
- **Consistency**: Reduces confusion from similar but different type names  
- **Standards Compliance**: Aligns with vCard 4.0 (RFC 6350) recommendations
- **Deduplication**: Prevents multiple entries with functionally identical types

## What Gets Cleaned

### iOS Corruption Issues

- Removes `ITEM1.`, `ITEM2.`, etc. prefixes from property names
- Cleans up Apple-specific PRODID references
- Normalizes type parameters to vCard 4.0 standard

### Data Standardization

- Converts all dates/timestamps to ISO 8601 format
- Enforces UTF-8 encoding throughout
- Removes obsolete parameters (CHARSET, etc.)
- Standardizes type values (HOME→home, WORK→work, CELL→cell)

### Content Processing

- Resizes oversized photos to reasonable dimensions
- Removes duplicate photos (keeps only the first occurrence)
- Cleans address fields of malformed linebreaks and escape sequences
- Generates new UIDs for contacts missing them
- Ensures all contacts have proper PRODID fields

### File Organization

- Option to split multi-contact files into individual contact files
- Automatic filename generation based on contact names
- Preserves directory structure and handles filename conflicts

## Technical Details

### vCard 4.0 (RFC 6350) Features

- UTF-8 encoding by default (no CHARSET parameter required)
- Lowercase type parameters for better compatibility
- ISO 8601 date/time formatting
- Modern property set including new vCard 4.0 properties
- Data URI format for binary data (photos, etc.)

### Photo Processing

- Automatic detection of oversized photos (>1MB)
- Intelligent resizing while maintaining aspect ratio
- JPEG optimization for file size reduction
- Base64 encoding cleanup and validation

### Error Handling

- Comprehensive validation of VCard structure
- Graceful handling of malformed entries
- Detailed error reporting and progress feedback
- Safe handling of missing or corrupted photos

## Output

The tool provides detailed feedback on processing results:

```text
VCard cleaning completed successfully!
==================================================
Input file: contacts.vcf
Output file: contacts_vcard40_cleaned.vcf
Total VCards processed: 150
iOS entries found: 127
Entries cleaned: 127
Photos processed: 45

File size reduction:
Original size: 2,847,392 characters
New size: 1,923,847 characters
Reduction: 923,545 characters (32.4%)
```

## License

This project is open source. Feel free to use, modify, and distribute according to your needs.

## Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.
